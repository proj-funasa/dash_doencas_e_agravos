"""
Retoma o bronze a partir de onde parou — pula tabelas que já existem no seaweedfs.bronze
"""
import os
import trino
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

DOENCAS = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

ANO_INICIO = '2007'
ANO_FIM    = '2025'
BATCH_SIZE = 2000

SQLSERVER_URL  = os.environ["SQLSERVER_URL"]
TRINO_HOST     = os.environ["TRINO_HOST"]
TRINO_PORT     = int(os.environ.get("TRINO_PORT", 443))
TRINO_USER     = os.environ["TRINO_USER"]
TRINO_PASSWORD = os.environ["TRINO_PASSWORD"]


def log(msg):
    print(f"[BRONZE] {msg}", flush=True)


def get_trino():
    return trino.dbapi.connect(
        host=TRINO_HOST, port=TRINO_PORT, user=TRINO_USER,
        http_scheme='https',
        auth=trino.auth.BasicAuthentication(TRINO_USER, TRINO_PASSWORD),
    )


def tabela_existe(cur, tabela):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {tabela}")
        n = cur.fetchone()[0]
        return n > 0
    except Exception:
        return False


def df_to_trino(cur, df, tabela_destino, ddl):
    cur.execute(f"DROP TABLE IF EXISTS {tabela_destino}")
    cur.execute(ddl)
    total = len(df)
    inseridos = 0
    import time
    t0 = time.time()
    for start in range(0, total, BATCH_SIZE):
        batch = df.iloc[start:start + BATCH_SIZE]
        valores = []
        for _, row in batch.iterrows():
            cells = []
            for val in row:
                if pd.isna(val) or val is None:
                    cells.append("NULL")
                elif isinstance(val, str):
                    cells.append(f"'{str(val).replace(chr(39), chr(39)*2)}'")
                elif isinstance(val, float):
                    cells.append(str(int(val)) if val == int(val) else str(val))
                else:
                    cells.append(str(val))
            valores.append(f"({', '.join(cells)})")
        cur.execute(f"INSERT INTO {tabela_destino} VALUES {', '.join(valores)}")
        inseridos += len(batch)
        elapsed = time.time() - t0
        pct = inseridos / total * 100
        eta = (elapsed / inseridos * (total - inseridos)) if inseridos > 0 else 0
        log(f"  {inseridos}/{total} ({pct:.0f}%) — {elapsed:.0f}s decorridos, ~{eta:.0f}s restantes")
    return inseridos


engine     = create_engine(SQLSERVER_URL)
trino_conn = get_trino()
cur        = trino_conn.cursor()

with engine.connect() as sql_conn:
    for doenca in DOENCAS:
        for tipo in ['anual', 'mensal']:
            src = f"SUS_SINAN_{doenca}_{tipo}"
            dst = f"seaweedfs.bronze.sinan_{doenca}_{tipo}"

            if tabela_existe(cur, dst):
                log(f"[SKIP] {dst} já existe")
                continue

            log(f"Gravando {src} → {dst}")
            log(f"  Lendo do SQL Server...")
            df = pd.read_sql(
                f"SELECT * FROM {src} WHERE ano BETWEEN '{ANO_INICIO}' AND '{ANO_FIM}'",
                sql_conn
            )
            df = df.fillna(0)
            df['codigo_municipio'] = df['codigo_municipio'].astype(str).str.strip()

            col_defs = []
            str_cols = {'codigo_municipio', 'ano', 'mes', 'tipo_municipio'}
            for col in df.columns:
                if col in str_cols:
                    col_defs.append(f"{col} VARCHAR")
                    df[col] = df[col].astype(str)
                else:
                    col_defs.append(f"{col} BIGINT")
                    df[col] = df[col].astype(int)

            log(f"  Leitura concluída: {len(df)} linhas. Iniciando INSERT no Trino...")
            ddl = f"CREATE TABLE {dst} ({', '.join(col_defs)}) WITH (format = 'PARQUET')"
            n = df_to_trino(cur, df, dst, ddl)
            log(f"  → {n} linhas gravadas em {dst}")

engine.dispose()
trino_conn.close()
log("Bronze concluído.")