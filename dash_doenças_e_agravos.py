import dash
from dash import dcc, html, Input, Output
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import create_engine

# ── Conexão ──────────────────────────────────────────────────────────────────
engine = create_engine(
    "mssql+pymssql://public_sqlserver:funasa@funasadb.dataiesb.com/Saneamento"
)
conn = engine.connect()

# Lista de doenças disponíveis
doencas = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

# Nomes formatados para exibição
nomes_exibicao = {
    'botulismo': 'Botulismo',
    'chagas': 'Chagas',
    'colera': 'Cólera',
    'dengue_antigo': 'Dengue (antigo)',
    'dengue': 'Dengue',
    'esquistossomose': 'Esquistossomose',
    'febre_tifoide': 'Febre Tifoide',
    'hepatites': 'Hepatites',
    'malaria': 'Malária',
    'toxo_congenita': 'Toxo. Congênita',
    'toxo_gestacional': 'Toxo. Gestacional'
}

# Soma total de casos por doença (2007 a 2025)
resultados = []
for doenca in doencas:
    tabela = f"SUS_SINAN_{doenca}_anual"
    query = f"""
        SELECT SUM(CAST(casos_ano AS BIGINT)) AS total_casos
        FROM {tabela}
        WHERE ano BETWEEN '2007' AND '2025'
    """
    df = pd.read_sql(query, conn)
    total = df['total_casos'].iloc[0] or 0
    resultados.append({'doenca': doenca, 'total_casos': int(total)})

df_total = pd.DataFrame(resultados)

# ── Carregar tabela de municípios ────────────────────────────────────────────
df_municipios = pd.read_sql("SELECT codigo_municipio, nome_municipio FROM Municipio", conn)
df_municipios['nome_municipio'] = df_municipios['nome_municipio'].str.title()

# ── Mapeamento UF e Região pelo código IBGE (2 primeiros dígitos) ────────────
UF_POR_CODIGO = {
    '11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA',
    '16': 'AP', '17': 'TO', '21': 'MA', '22': 'PI', '23': 'CE',
    '24': 'RN', '25': 'PB', '26': 'PE', '27': 'AL', '28': 'SE',
    '29': 'BA', '31': 'MG', '32': 'ES', '33': 'RJ', '35': 'SP',
    '41': 'PR', '42': 'SC', '43': 'RS', '50': 'MS', '51': 'MT',
    '52': 'GO', '53': 'DF'
}

REGIAO_POR_UF = {
    'RO': 'Norte', 'AC': 'Norte', 'AM': 'Norte', 'RR': 'Norte',
    'PA': 'Norte', 'AP': 'Norte', 'TO': 'Norte',
    'MA': 'Nordeste', 'PI': 'Nordeste', 'CE': 'Nordeste', 'RN': 'Nordeste',
    'PB': 'Nordeste', 'PE': 'Nordeste', 'AL': 'Nordeste', 'SE': 'Nordeste',
    'BA': 'Nordeste',
    'MG': 'Sudeste', 'ES': 'Sudeste', 'RJ': 'Sudeste', 'SP': 'Sudeste',
    'PR': 'Sul', 'SC': 'Sul', 'RS': 'Sul',
    'MS': 'Centro-Oeste', 'MT': 'Centro-Oeste', 'GO': 'Centro-Oeste',
    'DF': 'Centro-Oeste'
}

df_municipios['codigo_municipio'] = df_municipios['codigo_municipio'].astype(str)
df_municipios['uf'] = df_municipios['codigo_municipio'].str[:2].map(UF_POR_CODIGO)
df_municipios['regiao'] = df_municipios['uf'].map(REGIAO_POR_UF)

# ── Carregar dados por município para cada doença (residência) ───────────────
# Vamos usar tipo_municipio = 'residencia' como padrão
dados_municipio = []
for doenca in doencas:
    tabela = f"SUS_SINAN_{doenca}_anual"
    query = f"""
        SELECT codigo_municipio, SUM(CAST(casos_ano AS BIGINT)) AS total_casos
        FROM {tabela}
        WHERE ano BETWEEN '2007' AND '2025'
        GROUP BY codigo_municipio
    """
    df_mun = pd.read_sql(query, conn)
    df_mun['doenca'] = doenca
    dados_municipio.append(df_mun)

conn.close()
engine.dispose()

df_casos_municipio = pd.concat(dados_municipio, ignore_index=True)
df_casos_municipio['codigo_municipio'] = df_casos_municipio['codigo_municipio'].astype(str)

# Merge com nomes
df_casos_municipio = df_casos_municipio.merge(df_municipios, on='codigo_municipio', how='left')

# ── Cores e Estilo ───────────────────────────────────────────────────────────
COR_HEADER = "#1B3A5C"
COR_FUNDO = "#F0F2F5"

CORES_DOENCAS = [
    "#2B6CB0", "#2F855A", "#D85A30", "#7F77DD", "#1D9E75",
    "#EF9F27", "#378ADD", "#C53030", "#5A6B7A", "#9F7AEA", "#DD6B20"
]

COR_POR_DOENCA = {d: CORES_DOENCAS[i] for i, d in enumerate(doencas)}


# ── Funções auxiliares de Layout ─────────────────────────────────────────────
def _kpi(nome, valor, cor):
    return html.Div([
        html.P(
            f"{valor:,.0f}".replace(",", "."),
            style={
                "fontSize": 26, "fontWeight": 700, "color": "#fff",
                "margin": "0 0 4px 0"
            }
        ),
        html.P(
            nome,
            style={
                "fontSize": 11, "fontWeight": 600, "color": "#fff",
                "margin": 0, "textTransform": "uppercase",
                "letterSpacing": "0.05em"
            }
        ),
    ], style={
        "backgroundColor": cor, "borderRadius": 8,
        "padding": "18px 22px", "flex": 1, "minWidth": "200px"
    })


def _card(children):
    return html.Div(
        children,
        style={
            "backgroundColor": "#ffffff", "borderRadius": 8,
            "padding": "20px 24px", "border": "1px solid #e2e8f0",
            "flex": 1
        },
    )


def _titulo(texto):
    return html.P(
        texto,
        style={
            "fontSize": 13, "fontWeight": 600, "color": "#2d3748", "margin": 0
        }
    )


# ── Gráfico de Barras Horizontal (total por doença) ─────────────────────────
df_sorted = df_total.sort_values("total_casos", ascending=True)

fig_barras = go.Figure(go.Bar(
    x=df_sorted["total_casos"],
    y=[nomes_exibicao[d] for d in df_sorted["doenca"]],
    orientation="h",
    marker_color=[COR_POR_DOENCA[d] for d in df_sorted["doenca"]],
    hovertemplate="<b>%{y}</b><br>Casos: %{x:,.0f}<extra></extra>",
))

fig_barras.update_layout(
    margin=dict(l=10, r=20, t=10, b=40),
    plot_bgcolor="#ffffff",
    paper_bgcolor="#ffffff",
    font=dict(family="Inter, sans-serif", size=12, color="#333"),
    xaxis=dict(showgrid=True, gridcolor="#f0f0f0", linecolor="#e0e0e0", title="Total de Casos"),
    yaxis=dict(showgrid=False, linecolor="#e0e0e0"),
    hoverlabel=dict(bgcolor="#fff", bordercolor="#ccc", font_size=12),
    height=420,
)

# ── Listas para filtros ──────────────────────────────────────────────────────
regioes = sorted(df_casos_municipio['regiao'].dropna().unique())
ufs = sorted(df_casos_municipio['uf'].dropna().unique())

# ── App ──────────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    title="Doenças e Agravos — SINAN",
    suppress_callback_exceptions=True,
)
server = app.server

# KPIs
kpis = []
for _, row in df_total.iterrows():
    cor = COR_POR_DOENCA[row['doenca']]
    kpis.append(_kpi(nomes_exibicao[row['doenca']], row['total_casos'], cor))

app.layout = html.Div(
    style={
        "fontFamily": "Inter, sans-serif",
        "backgroundColor": COR_FUNDO,
        "minHeight": "100vh"
    },
    children=[
        # Header
        html.Div([
            html.Img(
                src="/assets/logo_funasa.png",
                style={"height": "50px", "marginRight": "20px"}
            ),
            html.Div([
                html.P("FUNASA", style={
                    "fontSize": 10, "color": "#8BAFC8", "margin": "0 0 2px 0",
                    "letterSpacing": "0.1em", "fontWeight": 600
                }),
                html.H1("Doenças e Agravos — Casos Notificados", style={
                    "fontSize": 22, "fontWeight": 700, "color": "#fff", "margin": 0
                }),
                html.P(
                    "Total de casos notificados por doença (2007–2025) · Fonte: SINAN/DATASUS",
                    style={"fontSize": 12, "color": "#8BAFC8", "margin": "4px 0 0 0"}
                ),
            ], style={"flex": 1}),
            html.Div([
                html.P(f"{len(doencas)}", style={
                    "fontSize": 28, "fontWeight": 700, "color": "#fff",
                    "margin": 0, "textAlign": "center"
                }),
                html.P("DOENÇAS", style={
                    "fontSize": 10, "color": "#8BAFC8", "margin": 0,
                    "textAlign": "center", "letterSpacing": "0.05em"
                }),
            ], style={
                "backgroundColor": "#2d4a6b", "borderRadius": 8, "padding": "12px 20px"
            }),
        ], style={
            "backgroundColor": COR_HEADER, "padding": "20px 32px",
            "display": "flex", "alignItems": "center", "justifyContent": "space-between"
        }),

        # Conteúdo
        html.Div(style={"padding": "24px 32px"}, children=[

            # Título dos KPIs
            html.P(
                "Total de casos notificados por doença no período de 2007 a 2025",
                style={"fontSize": 14, "fontWeight": 600, "color": "#2d3748", "marginBottom": 12}
            ),

            # KPIs
            html.Div(kpis, style={
                "display": "flex", "gap": 12, "marginBottom": 20, "flexWrap": "wrap"
            }),

            # Gráfico de barras total
            _card([
                _titulo("Total de Casos por Doença (2007–2025)"),
                dcc.Graph(figure=fig_barras, config={"displayModeBar": False}),
            ]),

            # ── Seção: Análise por Município ─────────────────────────────────
            html.Div(style={"marginTop": 24}, children=[
                _card([
                    _titulo("Top 10 Municípios por Casos Notificados"),

                    # Filtros
                    html.Div([
                        html.Div([
                            html.Label("Doença", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="filtro-doenca",
                                options=[{"label": nomes_exibicao[d], "value": d} for d in doencas],
                                value="dengue",
                                clearable=False,
                                style={"width": "180px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Região", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="filtro-regiao",
                                options=[{"label": "Todas", "value": "Todos"}] +
                                        [{"label": r, "value": r} for r in regioes],
                                value="Todos",
                                clearable=False,
                                style={"width": "160px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("UF", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="filtro-uf",
                                options=[{"label": "Todas", "value": "Todos"}] +
                                        [{"label": uf, "value": uf} for uf in ufs],
                                value="Todos",
                                clearable=False,
                                style={"width": "120px", "fontSize": 13},
                            ),
                        ]),
                    ], style={"display": "flex", "gap": 16, "marginTop": 16, "marginBottom": 20}),

                    # Gráfico + Tabela
                    html.Div([
                        html.Div(id="grafico-top10", style={"flex": 1}),
                        html.Div(id="tabela-municipios", style={
                            "flex": 1, "borderLeft": "1px solid #e2e8f0",
                            "paddingLeft": "20px", "maxHeight": "420px", "overflowY": "auto"
                        }),
                    ], style={"display": "flex", "gap": 20, "alignItems": "flex-start"}),
                ]),
            ]),
        ]),
    ]
)


# ── Callback: Atualizar gráfico e tabela por município ───────────────────────
@app.callback(
    [Output("grafico-top10", "children"), Output("tabela-municipios", "children")],
    [Input("filtro-doenca", "value"), Input("filtro-regiao", "value"), Input("filtro-uf", "value")]
)
def atualizar_municipios(doenca_sel, regiao_sel, uf_sel):
    df_filtrado = df_casos_municipio[df_casos_municipio['doenca'] == doenca_sel].copy()

    if regiao_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado['regiao'] == regiao_sel]
    if uf_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado['uf'] == uf_sel]

    df_filtrado = df_filtrado.dropna(subset=['nome_municipio'])
    df_filtrado = df_filtrado.sort_values("total_casos", ascending=False)

    # Top 10 para o gráfico
    top10 = df_filtrado.head(10).sort_values("total_casos", ascending=True)

    fig = go.Figure(go.Bar(
        x=top10["total_casos"],
        y=top10["nome_municipio"] + " (" + top10["uf"].fillna("") + ")",
        orientation="h",
        marker_color=COR_POR_DOENCA[doenca_sel],
        hovertemplate="<b>%{y}</b><br>Casos: %{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font=dict(family="Inter, sans-serif", size=12, color="#333"),
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0", title="Total de Casos"),
        yaxis=dict(showgrid=False),
        height=380,
    )

    grafico = dcc.Graph(figure=fig, config={"displayModeBar": False})

    # Tabela com top 50
    top50 = df_filtrado.head(50)
    colunas = ["Município", "UF", "Região", "Total de Casos"]
    header = html.Tr([
        html.Th(col, style={
            "padding": "10px 12px", "textAlign": "left", "fontSize": 11,
            "fontWeight": 600, "color": "#4a5568", "borderBottom": "2px solid #e2e8f0",
            "textTransform": "uppercase", "letterSpacing": "0.03em"
        }) for col in colunas
    ])

    rows = []
    for _, row in top50.iterrows():
        cells = [
            html.Td(row["nome_municipio"] or "—", style={"padding": "7px 12px", "fontSize": 12, "borderBottom": "1px solid #f0f0f0"}),
            html.Td(row["uf"] or "—", style={"padding": "7px 12px", "fontSize": 12, "borderBottom": "1px solid #f0f0f0"}),
            html.Td(row["regiao"] or "—", style={"padding": "7px 12px", "fontSize": 12, "borderBottom": "1px solid #f0f0f0"}),
            html.Td(
                f"{row['total_casos']:,.0f}".replace(",", "."),
                style={"padding": "7px 12px", "fontSize": 12, "fontWeight": 600, "borderBottom": "1px solid #f0f0f0"}
            ),
        ]
        rows.append(html.Tr(cells))

    tabela = html.Div([
        html.Table([html.Thead(header), html.Tbody(rows)], style={"width": "100%", "borderCollapse": "collapse"}),
        html.P(
            f"Exibindo {min(50, len(df_filtrado))} de {len(df_filtrado)} municípios",
            style={"fontSize": 11, "color": "#9ca3af", "margin": "12px 0 0 0"}
        ),
    ])

    return grafico, tabela


if __name__ == "__main__":
    app.run(debug=True, port=8051)
