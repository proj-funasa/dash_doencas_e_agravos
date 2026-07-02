import os
import trino
from dotenv import load_dotenv

load_dotenv()

DOENCAS = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

conn = trino.dbapi.connect(
    host=os.environ["TRINO_HOST"],
    port=int(os.environ.get("TRINO_PORT", 443)),
    user=os.environ["TRINO_USER"],
    http_scheme='https',
    auth=trino.auth.BasicAuthentication(os.environ["TRINO_USER"], os.environ["TRINO_PASSWORD"]),
)
cur = conn.cursor()

print("=== STATUS BRONZE ===")
for doenca in DOENCAS:
    for tipo in ['anual', 'mensal']:
        tabela = f"seaweedfs.bronze.sinan_{doenca}_{tipo}"
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tabela}")
            n = cur.fetchone()[0]
            status = f"OK  {n:>8} linhas"
        except Exception:
            status = "FALTA"
        print(f"  [{status}]  {tabela}")

# municipio
try:
    cur.execute("SELECT COUNT(*) FROM seaweedfs.bronze.municipio")
    print(f"\n  [OK  {cur.fetchone()[0]:>8} linhas]  seaweedfs.bronze.municipio")
except Exception:
    print("\n  [FALTA]  seaweedfs.bronze.municipio")

conn.close()