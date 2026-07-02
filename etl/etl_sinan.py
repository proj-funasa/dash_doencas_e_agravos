"""
ETL SINAN — Bronze → Silver → Gold
===================================
Bronze : lê do SQL Server via pymssql, grava no seaweedfs.bronze via Trino (INSERT)
Silver : limpeza, tipagem e enriquecimento com UF/Região (CTAS dentro do seaweedfs)
Gold   : tabelas agregadas prontas para o dashboard (CTAS dentro do seaweedfs)

Execução:
    python etl_sinan.py            # roda tudo
    python etl_sinan.py bronze     # só bronze
    python etl_sinan.py silver     # só silver
    python etl_sinan.py gold       # só gold
"""

import os
import sys
import trino
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# ── Configuração ──────────────────────────────────────────────────────────────
DOENCAS = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

ANO_INICIO = '2007'
ANO_FIM    = '2025'

BATCH_SIZE = 2000  # linhas por INSERT

# SQL Server (fonte)
SQLSERVER_URL = os.environ["SQLSERVER_URL"]

# Trino (destino)
TRINO_HOST     = os.environ["TRINO_HOST"]
TRINO_PORT     = int(os.environ.get("TRINO_PORT", 443))
TRINO_USER     = os.environ["TRINO_USER"]
TRINO_PASSWORD = os.environ["TRINO_PASSWORD"]

# Mapeamentos geográficos (usados no silver via Python para evitar JOIN cross-catalog)
UF_POR_CODIGO = {
    '11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA',
    '16': 'AP', '17': 'TO', '21': 'MA', '22': 'PI', '23': 'CE',
    '24': 'RN', '25': 'PB', '26': 'PE', '27': 'AL', '28': 'SE',
    '29': 'BA', '31': 'MG', '32': 'ES', '33': 'RJ', '35': 'SP',
    '41': 'PR', '42': 'SC', '43': 'RS', '50': 'MS', '51': 'MT',
    '52': 'GO', '53': 'DF'
}

REGIAO_POR_UF = {
    'RO': 'Norte',    'AC': 'Norte',    'AM': 'Norte',    'RR': 'Norte',
    'PA': 'Norte',    'AP': 'Norte',    'TO': 'Norte',
    'MA': 'Nordeste', 'PI': 'Nordeste', 'CE': 'Nordeste', 'RN': 'Nordeste',
    'PB': 'Nordeste', 'PE': 'Nordeste', 'AL': 'Nordeste', 'SE': 'Nordeste',
    'BA': 'Nordeste',
    'MG': 'Sudeste',  'ES': 'Sudeste',  'RJ': 'Sudeste',  'SP': 'Sudeste',
    'PR': 'Sul',      'SC': 'Sul',      'RS': 'Sul',
    'MS': 'Centro-Oeste', 'MT': 'Centro-Oeste',
    'GO': 'Centro-Oeste', 'DF': 'Centro-Oeste'
}


def log(msg):
    print(f"[ETL] {msg}", flush=True)


def get_trino():
    return trino.dbapi.connect(
        host=TRINO_HOST,
        port=TRINO_PORT,
        user=TRINO_USER,
        http_scheme='https',
        auth=trino.auth.BasicAuthentication(TRINO_USER, TRINO_PASSWORD),
    )


def get_sqlserver():
    return create_engine(SQLSERVER_URL)


def trino_execute(cur, sql, descricao=""):
    """Executa SQL no Trino com log de erro."""
    try:
        cur.execute(sql)
        return True
    except Exception as e:
        log(f"  [ERRO] {descricao}: {e}")
        return False


def df_to_trino(cur, df, tabela_destino, ddl):
    """
    Recria a tabela no Trino e insere o DataFrame em batches.
    ddl: CREATE TABLE ... (col1 TYPE, col2 TYPE, ...)
    """
    cur.execute(f"DROP TABLE IF EXISTS {tabela_destino}")
    cur.execute(ddl)

    total = len(df)
    inseridos = 0

    for start in range(0, total, BATCH_SIZE):
        batch = df.iloc[start:start + BATCH_SIZE]
        valores = []
        for _, row in batch.iterrows():
            cells = []
            for val in row:
                if pd.isna(val) or val is None:
                    cells.append("NULL")
                elif isinstance(val, str):
                    val_esc = str(val).replace("'", "''")
                    cells.append(f"'{val_esc}'")
                elif isinstance(val, float):
                    cells.append(str(int(val)) if val == int(val) else str(val))
                else:
                    cells.append(str(val))
            valores.append(f"({', '.join(cells)})")

        insert_sql = f"INSERT INTO {tabela_destino} VALUES {', '.join(valores)}"
        cur.execute(insert_sql)
        inseridos += len(batch)
        log(f"    {inseridos}/{total} linhas inseridas...")

    return inseridos


# ─────────────────────────────────────────────────────────────────────────────
# BRONZE: SQL Server → seaweedfs.bronze
# ─────────────────────────────────────────────────────────────────────────────
def run_bronze():
    log("=== INICIANDO BRONZE ===")

    engine = get_sqlserver()
    trino_conn = get_trino()
    cur = trino_conn.cursor()

    with engine.connect() as sql_conn:

        # ── Tabela de municípios ──────────────────────────────────────────
        log("Bronze: Municipio")
        df_mun = pd.read_sql(
            "SELECT codigo_municipio, nome_municipio FROM Municipio",
            sql_conn
        )
        df_mun['codigo_municipio'] = df_mun['codigo_municipio'].astype(str).str.strip()
        df_mun['nome_municipio']   = df_mun['nome_municipio'].astype(str).str.strip().str.title()

        ddl = """
            CREATE TABLE seaweedfs.bronze.municipio (
                codigo_municipio VARCHAR,
                nome_municipio   VARCHAR
            ) WITH (format = 'PARQUET')
        """
        n = df_to_trino(cur, df_mun, "seaweedfs.bronze.municipio", ddl)
        log(f"  → {n} municípios gravados")

        # ── Tabelas SINAN ─────────────────────────────────────────────────
        for doenca in DOENCAS:

            # --- Anual ---
            tabela_src = f"SUS_SINAN_{doenca}_anual"
            tabela_dst = f"seaweedfs.bronze.sinan_{doenca}_anual"
            log(f"Bronze anual: {tabela_src} → {tabela_dst}")

            df = pd.read_sql(
                f"SELECT * FROM {tabela_src} WHERE ano BETWEEN '{ANO_INICIO}' AND '{ANO_FIM}'",
                sql_conn
            )
            df = df.fillna(0)
            df['codigo_municipio'] = df['codigo_municipio'].astype(str).str.strip()

            # Monta DDL com as colunas do DataFrame
            col_defs = []
            for col in df.columns:
                dtype = df[col].dtype
                if col in ('codigo_municipio', 'ano', 'tipo_municipio'):
                    col_defs.append(f"{col} VARCHAR")
                else:
                    col_defs.append(f"{col} BIGINT")
            ddl = f"""
                CREATE TABLE {tabela_dst} (
                    {', '.join(col_defs)}
                ) WITH (format = 'PARQUET')
            """
            # Converte colunas numéricas para int
            for col in df.select_dtypes(include=['float', 'int']).columns:
                df[col] = df[col].astype(int)

            n = df_to_trino(cur, df, tabela_dst, ddl)
            log(f"  → {n} linhas gravadas")

            # --- Mensal ---
            tabela_src = f"SUS_SINAN_{doenca}_mensal"
            tabela_dst = f"seaweedfs.bronze.sinan_{doenca}_mensal"
            log(f"Bronze mensal: {tabela_src} → {tabela_dst}")

            df = pd.read_sql(
                f"SELECT * FROM {tabela_src} WHERE ano BETWEEN '{ANO_INICIO}' AND '{ANO_FIM}'",
                sql_conn
            )
            df = df.fillna(0)
            df['codigo_municipio'] = df['codigo_municipio'].astype(str).str.strip()

            col_defs = []
            for col in df.columns:
                if col in ('codigo_municipio', 'ano', 'mes', 'tipo_municipio'):
                    col_defs.append(f"{col} VARCHAR")
                else:
                    col_defs.append(f"{col} BIGINT")
            ddl = f"""
                CREATE TABLE {tabela_dst} (
                    {', '.join(col_defs)}
                ) WITH (format = 'PARQUET')
            """
            for col in df.select_dtypes(include=['float', 'int']).columns:
                df[col] = df[col].astype(int)

            n = df_to_trino(cur, df, tabela_dst, ddl)
            log(f"  → {n} linhas gravadas")

    engine.dispose()
    trino_conn.close()
    log("=== BRONZE CONCLUÍDO ===\n")


# ─────────────────────────────────────────────────────────────────────────────
# SILVER: seaweedfs.bronze → seaweedfs.silver  (CTAS dentro do seaweedfs)
# ─────────────────────────────────────────────────────────────────────────────
def run_silver():
    log("=== INICIANDO SILVER ===")
    conn = get_trino()
    cur = conn.cursor()

    for doenca in DOENCAS:

        # --- Anual ---
        dst = f"seaweedfs.silver.sinan_{doenca}_anual"
        log(f"Silver anual: {dst}")
        sql = f"""
            CREATE TABLE {dst}
            WITH (format = 'PARQUET')
            AS
            SELECT
                b.codigo_municipio,
                m.nome_municipio,
                b.ano,
                b.tipo_municipio,
                b.casos_ano,
                b.faixa_etaria_1_ano      AS faixa_etaria_menor_1,
                b.faixa_etaria_1_4,
                b.faixa_etaria_5_9,
                b.faixa_etaria_10_14,
                b.faixa_etaria_15_19,
                b.faixa_etaria_20_39,
                b.faixa_etaria_40_59,
                b.faixa_etaria_60_64,
                b.faixa_etaria_65_69,
                b.faixa_etaria_70_79,
                b.sexo_masculino,
                b.sexo_feminino,
                b.raca_branca,
                b.raca_preta,
                b.raca_parda,
                b.raca_amarela,
                b.raca_indigena,
                b.evolucao_cura,
                b.evolucao_obito_pelo_agravo_notificado   AS evolucao_obito_agravo,
                b.evolucao_obito_por_outra_causa          AS evolucao_obito_outra,
                b.evolucao_obito_em_investigacao          AS evolucao_obito_investigacao,
                b.zona_urbana,
                b.zona_rural,
                '{doenca}' AS doenca
            FROM seaweedfs.bronze.sinan_{doenca}_anual b
            LEFT JOIN seaweedfs.bronze.municipio m
                   ON b.codigo_municipio = m.codigo_municipio
        """
        cur.execute(f"DROP TABLE IF EXISTS {dst}")
        if trino_execute(cur, sql, dst):
            cur.execute(f"SELECT COUNT(*) FROM {dst}")
            log(f"  → {cur.fetchone()[0]} linhas")

        # --- Mensal ---
        dst = f"seaweedfs.silver.sinan_{doenca}_mensal"
        log(f"Silver mensal: {dst}")
        sql = f"""
            CREATE TABLE {dst}
            WITH (format = 'PARQUET')
            AS
            SELECT
                b.codigo_municipio,
                m.nome_municipio,
                b.ano,
                b.mes,
                b.tipo_municipio,
                b.casos_mes,
                '{doenca}' AS doenca
            FROM seaweedfs.bronze.sinan_{doenca}_mensal b
            LEFT JOIN seaweedfs.bronze.municipio m
                   ON b.codigo_municipio = m.codigo_municipio
        """
        cur.execute(f"DROP TABLE IF EXISTS {dst}")
        if trino_execute(cur, sql, dst):
            cur.execute(f"SELECT COUNT(*) FROM {dst}")
            log(f"  → {cur.fetchone()[0]} linhas")

    conn.close()
    log("=== SILVER CONCLUÍDO ===\n")


# ─────────────────────────────────────────────────────────────────────────────
# GOLD: seaweedfs.silver → seaweedfs.gold  (agregações para o dashboard)
# ─────────────────────────────────────────────────────────────────────────────
def run_gold():
    log("=== INICIANDO GOLD ===")
    conn = get_trino()
    cur = conn.cursor()

    # ── gold.kpi_total_por_doenca ─────────────────────────────────────────
    # Uma linha por doença com total de casos no período — usado nos KPIs
    log("Gold: kpi_total_por_doenca")
    cur.execute("DROP TABLE IF EXISTS seaweedfs.gold.kpi_total_por_doenca")
    unions = "\nUNION ALL\n".join([
        f"SELECT '{d}' AS doenca, SUM(casos_ano) AS total_casos "
        f"FROM seaweedfs.silver.sinan_{d}_anual "
        f"WHERE tipo_municipio = 'residencia'"
        for d in DOENCAS
    ])
    sql = f"""
        CREATE TABLE seaweedfs.gold.kpi_total_por_doenca
        WITH (format = 'PARQUET')
        AS
        SELECT doenca, SUM(total_casos) AS total_casos
        FROM ({unions}) t
        GROUP BY doenca
    """
    if trino_execute(cur, sql, "kpi_total_por_doenca"):
        cur.execute("SELECT COUNT(*) FROM seaweedfs.gold.kpi_total_por_doenca")
        log(f"  → {cur.fetchone()[0]} linhas")

    # ── gold.casos_por_municipio_ano ──────────────────────────────────────
    # Casos agregados por município + ano + doença — usado no top 10 e tabela
    log("Gold: casos_por_municipio_ano")
    cur.execute("DROP TABLE IF EXISTS seaweedfs.gold.casos_por_municipio_ano")
    unions = "\nUNION ALL\n".join([
        f"SELECT codigo_municipio, nome_municipio, ano, '{d}' AS doenca, "
        f"SUM(casos_ano) AS casos_ano "
        f"FROM seaweedfs.silver.sinan_{d}_anual "
        f"WHERE tipo_municipio = 'residencia' "
        f"GROUP BY codigo_municipio, nome_municipio, ano"
        for d in DOENCAS
    ])
    sql = f"""
        CREATE TABLE seaweedfs.gold.casos_por_municipio_ano
        WITH (format = 'PARQUET')
        AS {unions}
    """
    if trino_execute(cur, sql, "casos_por_municipio_ano"):
        cur.execute("SELECT COUNT(*) FROM seaweedfs.gold.casos_por_municipio_ano")
        log(f"  → {cur.fetchone()[0]} linhas")

    # ── gold.casos_mensais ────────────────────────────────────────────────
    # Série temporal mensal por município + doença
    log("Gold: casos_mensais")
    cur.execute("DROP TABLE IF EXISTS seaweedfs.gold.casos_mensais")
    unions = "\nUNION ALL\n".join([
        f"SELECT codigo_municipio, nome_municipio, ano, mes, '{d}' AS doenca, "
        f"SUM(casos_mes) AS casos_mes "
        f"FROM seaweedfs.silver.sinan_{d}_mensal "
        f"WHERE tipo_municipio = 'residencia' "
        f"GROUP BY codigo_municipio, nome_municipio, ano, mes"
        for d in DOENCAS
    ])
    sql = f"""
        CREATE TABLE seaweedfs.gold.casos_mensais
        WITH (format = 'PARQUET')
        AS {unions}
    """
    if trino_execute(cur, sql, "casos_mensais"):
        cur.execute("SELECT COUNT(*) FROM seaweedfs.gold.casos_mensais")
        log(f"  → {cur.fetchone()[0]} linhas")

    conn.close()
    log("=== GOLD CONCLUÍDO ===\n")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    etapa = sys.argv[1] if len(sys.argv) > 1 else 'all'

    if etapa in ('bronze', 'all'):
        run_bronze()
    if etapa in ('silver', 'all'):
        run_silver()
    if etapa in ('gold', 'all'):
        run_gold()

    log("ETL finalizado.")