## 📋 Sobre o projeto

Este projeto apresenta um painel web para acompanhamento do total de casos notificados de
**11 doenças e agravos** no período de **2007 a 2025**, com dados extraídos do
**SINAN (Sistema de Informação de Agravos de Notificação)** do DATASUS.

O dashboard permite:

- Visualizar o **total de casos por doença** em todo o período.
- Consultar o **ranking dos 10 municípios** com mais casos notificados para uma doença específica.
- Filtrar os dados por **doença**, **ano**, **região** e **UF**.
- Explorar uma **tabela detalhada** com os 50 municípios com mais casos, incluindo UF e região.

### Doenças e agravos monitorados

| | | |
|---|---|---|
| Botulismo | Chagas | Cólera |
| Dengue (antigo) | Dengue | Esquistossomose |
| Febre Tifoide | Hepatites | Malária |
| Toxoplasmose Congênita | Toxoplasmose Gestacional | |

## 🖼️ Estrutura do painel

- **Cabeçalho** com identidade visual da FUNASA e contagem de doenças monitoradas.
- **Cartões de KPI** com o total de casos notificados por doença.
- **Gráfico de barras horizontais** com o total de casos por doença (2007–2025).
- **Filtros interativos**: Doença, Ano, Região e UF (com UF cascateando conforme a região selecionada).
- **Gráfico Top 10 municípios** e **tabela com os 50 principais municípios** para os filtros aplicados.

## 🗂️ Estrutura do repositório

```
dash_doencas_e_agravos/
├── assets/                      # Arquivos estáticos servidos pelo Dash (CSS, imagens, etc.)
├── etl/                         # Scripts de ETL / preparação dos dados na camada gold
│   ├── etl_sinan.py             # Pipeline completo: Bronze → Silver → Gold
│   ├── bronze_resume.py         # Retoma a carga da camada Bronze de onde parou
│   ├── silver_gold.py           # Roda apenas as etapas Silver e Gold
│   ├── check_bronze.py          # Verifica o status das tabelas Bronze
│   └── create_gold_municipio.py # Cria a tabela agregada por município
├── dash_doenças_e_agravos.py    # Aplicação principal do dashboard (Dash)
├── logo_funasa.png              # Logo exibido no cabeçalho do painel
├── requirements.txt             # Dependências Python do projeto
├── .env.example                 # Modelo das variáveis de ambiente necessárias
└── .gitignore                   # Garante que o .env real não seja commitado
```

## 🛠️ Tecnologias utilizadas

- [Dash](https://dash.plotly.com/) — framework para construção do dashboard web
- [Plotly](https://plotly.com/python/) — geração dos gráficos
- [Pandas](https://pandas.pydata.org/) — manipulação e tratamento dos dados
- [Trino](https://trino.io/) — engine de consulta SQL distribuída, usada para acessar os dados na camada *gold* (via `python-trino`)
- [python-dotenv](https://pypi.org/project/python-dotenv/) — carrega variáveis de ambiente do arquivo `.env`


## ▶️ Executando o dashboard

Com as dependências instaladas e o `.env` configurado, execute:

```bash
python "dash_doenças_e_agravos.py"
```

O servidor será iniciado em modo debug na porta `8051`. Acesse no navegador:

```
http://localhost:8051
```

## 🔄 Executando o ETL (opcional)

Os scripts em `etl/` recriam as camadas Bronze, Silver e Gold no Trino a partir da
fonte original (SQL Server). Eles também dependem do `.env` configurado.

```bash
python etl/etl_sinan.py            # roda o pipeline completo
python etl/etl_sinan.py bronze     # roda apenas a camada Bronze
python etl/etl_sinan.py silver     # roda apenas a camada Silver
python etl/etl_sinan.py gold       # roda apenas a camada Gold

python etl/bronze_resume.py        # retoma a carga da Bronze de onde parou
python etl/silver_gold.py          # roda Silver + Gold sem tocar na Bronze
python etl/check_bronze.py         # verifica quais tabelas Bronze já existem
python etl/create_gold_municipio.py  # recria a tabela agregada por município
```
