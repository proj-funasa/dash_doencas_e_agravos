import trino

DOENCAS = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

conn = trino.dbapi.connect(
    host='trino.dataiesb.com', port=443, user='admin',
    http_scheme='https',
    auth=trino.auth.BasicAuthentication('admin', 'JGtHJlSQV5TqDh8jJJ1U0u6WyaSUxeLW'),
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
