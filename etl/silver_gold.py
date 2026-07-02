"""
Silver e Gold — roda CTAS dentro do seaweedfs (sem SQL Server)
"""
import sys
import trino

DOENCAS = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

TRINO_HOST     = 'trino.dataiesb.com'
TRINO_PORT     = 443
TRINO_USER     = 'admin'
TRINO_PASSWORD = 'JGtHJlSQV5TqDh8jJJ1U0u6WyaSUxeLW'


def log(msg):
    print(f"[ETL] {msg}", flush=True)


def get_trino():
    return trino.dbapi.connect(
        host=TRINO_HOST, port=TRINO_PORT, user=TRINO_USER,
        http_scheme='https',
        auth=trino.auth.BasicAuthentication(TRINO_USER, TRINO_PASSWORD),
    )


def exec_sql(cur, sql, nome=""):
    try:
        cur.execute(sql)
        return True
    except Exception as e:
        log(f"  [ERRO] {nome}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
def run_silver(cur):
    log("=== SILVER ===")
    for doenca in DOENCAS:

        # Anual — monta SELECT dinamicamente com as colunas disponíveis
        dst = f"seaweedfs.silver.sinan_{doenca}_anual"
        log(f"Silver anual → {dst}")
        cur.execute(f"DROP TABLE IF EXISTS {dst}")

        # Descobre colunas disponíveis no bronze
        cur.execute(f"DESCRIBE seaweedfs.bronze.sinan_{doenca}_anual")
        colunas_bronze = {row[0].lower() for row in cur.fetchall()}

        def col(nome, alias=None):
            """Retorna a coluna se existir, senão BIGINT 0 com alias."""
            a = alias or nome
            if nome in colunas_bronze:
                return f"b.{nome} AS {a}"
            return f"CAST(0 AS BIGINT) AS {a}"

        select = f"""
            SELECT
                b.codigo_municipio,
                m.nome_municipio,
                b.ano,
                b.tipo_municipio,
                b.casos_ano,
                {col('faixa_etaria_1_ano',  'faixa_etaria_menor_1')},
                {col('faixa_etaria_1_4')},
                {col('faixa_etaria_5_9')},
                {col('faixa_etaria_10_14')},
                {col('faixa_etaria_15_19')},
                {col('faixa_etaria_20_39')},
                {col('faixa_etaria_40_59')},
                {col('faixa_etaria_60_64')},
                {col('faixa_etaria_65_69')},
                {col('faixa_etaria_70_79')},
                {col('sexo_masculino')},
                {col('sexo_feminino')},
                {col('raca_branca')},
                {col('raca_preta')},
                {col('raca_parda')},
                {col('raca_amarela')},
                {col('raca_indigena')},
                {col('evolucao_cura')},
                {col('evolucao_obito_pelo_agravo_notificado', 'evolucao_obito_agravo')},
                {col('evolucao_obito_por_outra_causa',        'evolucao_obito_outra')},
                {col('evolucao_obito_em_investigacao',        'evolucao_obito_investigacao')},
                {col('zona_urbana')},
                {col('zona_rural')},
                '{doenca}' AS doenca
            FROM seaweedfs.bronze.sinan_{doenca}_anual b
            LEFT JOIN seaweedfs.bronze.municipio m
                   ON b.codigo_municipio = m.codigo_municipio
        """
        ok = exec_sql(cur, f"""
            CREATE TABLE {dst}
            WITH (format = 'PARQUET')
            AS {select}
        """, dst)
        if ok:
            cur.execute(f"SELECT COUNT(*) FROM {dst}")
            log(f"  → {cur.fetchone()[0]} linhas")

        # Mensal
        dst = f"seaweedfs.silver.sinan_{doenca}_mensal"
        log(f"Silver mensal → {dst}")
        cur.execute(f"DROP TABLE IF EXISTS {dst}")
        ok = exec_sql(cur, f"""
            CREATE TABLE {dst}
            WITH (format = 'PARQUET')
            AS
            SELECT
                CAST(b.codigo_municipio AS VARCHAR(10)) AS codigo_municipio,
                CAST(m.nome_municipio   AS VARCHAR)     AS nome_municipio,
                CAST(b.ano              AS VARCHAR(4))  AS ano,
                CAST(b.mes              AS VARCHAR(2))  AS mes,
                CAST(b.tipo_municipio   AS VARCHAR)     AS tipo_municipio,
                b.casos_mes,
                '{doenca}' AS doenca
            FROM seaweedfs.bronze.sinan_{doenca}_mensal b
            LEFT JOIN seaweedfs.bronze.municipio m
                   ON b.codigo_municipio = m.codigo_municipio
        """, dst)
        if ok:
            cur.execute(f"SELECT COUNT(*) FROM {dst}")
            log(f"  → {cur.fetchone()[0]} linhas")

    log("=== SILVER CONCLUÍDO ===\n")


# ─────────────────────────────────────────────────────────────────────────────
def run_gold(cur):
    log("=== GOLD ===")

    # kpi_total_por_doenca
    log("Gold: kpi_total_por_doenca")
    cur.execute("DROP TABLE IF EXISTS seaweedfs.gold.kpi_total_por_doenca")
    unions = " UNION ALL ".join([
        f"SELECT '{d}' AS doenca, SUM(casos_ano) AS total_casos "
        f"FROM seaweedfs.silver.sinan_{d}_anual WHERE tipo_municipio = 'residencia'"
        for d in DOENCAS
    ])
    ok = exec_sql(cur, f"""
        CREATE TABLE seaweedfs.gold.kpi_total_por_doenca
        WITH (format = 'PARQUET')
        AS
        SELECT doenca, SUM(total_casos) AS total_casos
        FROM ({unions}) t
        GROUP BY doenca
    """, "kpi_total_por_doenca")
    if ok:
        cur.execute("SELECT COUNT(*) FROM seaweedfs.gold.kpi_total_por_doenca")
        log(f"  → {cur.fetchone()[0]} linhas")

    # casos_por_municipio_ano
    log("Gold: casos_por_municipio_ano")
    cur.execute("DROP TABLE IF EXISTS seaweedfs.gold.casos_por_municipio_ano")
    unions = " UNION ALL ".join([
        f"SELECT CAST(codigo_municipio AS VARCHAR(10)) AS codigo_municipio, "
        f"CAST(nome_municipio AS VARCHAR) AS nome_municipio, "
        f"CAST(ano AS VARCHAR(4)) AS ano, "
        f"'{d}' AS doenca, "
        f"SUM(casos_ano) AS casos_ano "
        f"FROM seaweedfs.silver.sinan_{d}_anual "
        f"WHERE tipo_municipio = 'residencia' "
        f"GROUP BY codigo_municipio, nome_municipio, ano"
        for d in DOENCAS
    ])
    ok = exec_sql(cur, f"""
        CREATE TABLE seaweedfs.gold.casos_por_municipio_ano
        WITH (format = 'PARQUET')
        AS {unions}
    """, "casos_por_municipio_ano")
    if ok:
        cur.execute("SELECT COUNT(*) FROM seaweedfs.gold.casos_por_municipio_ano")
        log(f"  → {cur.fetchone()[0]} linhas")

    # casos_mensais
    log("Gold: casos_mensais")
    cur.execute("DROP TABLE IF EXISTS seaweedfs.gold.casos_mensais")
    unions = " UNION ALL ".join([
        f"SELECT CAST(codigo_municipio AS VARCHAR(10)) AS codigo_municipio, "
        f"CAST(nome_municipio AS VARCHAR) AS nome_municipio, "
        f"CAST(ano AS VARCHAR(4)) AS ano, "
        f"CAST(mes AS VARCHAR(2)) AS mes, "
        f"'{d}' AS doenca, "
        f"SUM(casos_mes) AS casos_mes "
        f"FROM seaweedfs.silver.sinan_{d}_mensal "
        f"WHERE tipo_municipio = 'residencia' "
        f"GROUP BY codigo_municipio, nome_municipio, ano, mes"
        for d in DOENCAS
    ])
    ok = exec_sql(cur, f"""
        CREATE TABLE seaweedfs.gold.casos_mensais
        WITH (format = 'PARQUET')
        AS {unions}
    """, "casos_mensais")
    if ok:
        cur.execute("SELECT COUNT(*) FROM seaweedfs.gold.casos_mensais")
        log(f"  → {cur.fetchone()[0]} linhas")

    log("=== GOLD CONCLUÍDO ===\n")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    etapa = sys.argv[1] if len(sys.argv) > 1 else 'all'
    conn = get_trino()
    cur  = conn.cursor()

    if etapa in ('silver', 'all'):
        run_silver(cur)
    if etapa in ('gold', 'all'):
        run_gold(cur)

    conn.close()
    log("Concluído.")
