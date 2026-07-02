"""
Cria seaweedfs.gold.casos_por_municipio — agregado por município+doença (sem ano)
~30k linhas, ideal para cache em memória no dashboard
"""
import trino

conn = trino.dbapi.connect(
    host='trino.dataiesb.com', port=443, user='admin',
    http_scheme='https',
    auth=trino.auth.BasicAuthentication('admin', 'JGtHJlSQV5TqDh8jJJ1U0u6WyaSUxeLW'),
)
cur = conn.cursor()

print("Criando seaweedfs.gold.casos_por_municipio...", flush=True)
cur.execute("DROP TABLE IF EXISTS seaweedfs.gold.casos_por_municipio")

DOENCAS = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

unions = " UNION ALL ".join([
    f"SELECT CAST(codigo_municipio AS VARCHAR(10)) AS codigo_municipio, "
    f"CAST(nome_municipio AS VARCHAR) AS nome_municipio, "
    f"'{d}' AS doenca, "
    f"SUM(casos_ano) AS total_casos "
    f"FROM seaweedfs.silver.sinan_{d}_anual "
    f"WHERE tipo_municipio = 'residencia' "
    f"GROUP BY codigo_municipio, nome_municipio"
    for d in DOENCAS
])

cur.execute(f"""
    CREATE TABLE seaweedfs.gold.casos_por_municipio
    WITH (format = 'PARQUET')
    AS {unions}
""")

cur.execute("SELECT COUNT(*) FROM seaweedfs.gold.casos_por_municipio")
print(f"Criado com {cur.fetchone()[0]:,} linhas.")
conn.close()
