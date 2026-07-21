import os
import requests
import dash
from dash import dcc, html, Input, Output
import pandas as pd
import plotly.graph_objects as go
import trino

TRINO_HOST = os.getenv("TRINO_HOST", "trino.trino.svc.cluster.local")
TRINO_PORT = int(os.getenv("TRINO_PORT", "8080"))
TRINO_USER = os.getenv("TRINO_USER", "funasa_reader")

# ── Conexão Trino (interna k8s) ──────────────────────────────────────────────
def query(sql):
    """Abre conexão, executa query, retorna DataFrame e fecha."""
    conn = trino.dbapi.connect(
        host=TRINO_HOST,
        port=TRINO_PORT,
        user=TRINO_USER,
    )
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return pd.DataFrame(rows, columns=cols)

# ── Configuração ──────────────────────────────────────────────────────────────
doencas = [
    'botulismo', 'chagas', 'colera', 'dengue_antigo', 'dengue',
    'esquistossomose', 'febre_tifoide', 'hepatites', 'malaria',
    'toxo_congenita', 'toxo_gestacional'
]

nomes_exibicao = {
    'botulismo':        'Botulismo',
    'chagas':           'Chagas',
    'colera':           'Cólera',
    'dengue_antigo':    'Dengue (antigo)',
    'dengue':           'Dengue',
    'esquistossomose':  'Esquistossomose',
    'febre_tifoide':    'Febre Tifoide',
    'hepatites':        'Hepatites',
    'malaria':          'Malária',
    'toxo_congenita':   'Toxo. Congênita',
    'toxo_gestacional': 'Toxo. Gestacional'
}

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

UF_POR_REGIAO = {}
for uf, regiao in REGIAO_POR_UF.items():
    UF_POR_REGIAO.setdefault(regiao, []).append(uf)

# Listas de filtros estáticas (sem consulta ao banco)
regioes = sorted(set(REGIAO_POR_UF.values()))
ufs     = sorted(REGIAO_POR_UF.keys())
anos    = [str(a) for a in range(2007, 2026)]
meses   = [str(m).zfill(2) for m in range(1, 13)]

NOME_MES = {
    '01': 'Janeiro', '02': 'Fevereiro', '03': 'Março', '04': 'Abril',
    '05': 'Maio', '06': 'Junho', '07': 'Julho', '08': 'Agosto',
    '09': 'Setembro', '10': 'Outubro', '11': 'Novembro', '12': 'Dezembro'
}

# ── Carregar dados do Gold na inicialização ───────────────────────────────────
print("[DASH] Carregando KPIs...", flush=True)
df_total = query("SELECT doenca, total_casos FROM seaweedfs.gold.kpi_total_por_doenca")
df_total['total_casos'] = pd.to_numeric(df_total['total_casos'], errors='coerce').fillna(0).astype(int)
df_total = df_total.set_index('doenca').reindex(doencas).reset_index()

print("[DASH] Carregando casos mensais (com ano e mês)...", flush=True)
df_mun = query("SELECT codigo_municipio, nome_municipio, ano, mes, doenca, casos_mes FROM seaweedfs.gold.casos_mensais")
df_mun['codigo_municipio'] = df_mun['codigo_municipio'].astype(str).str.strip()
df_mun['nome_municipio']   = df_mun['nome_municipio'].str.title()
df_mun['casos_mes']        = pd.to_numeric(df_mun['casos_mes'], errors='coerce').fillna(0).astype(int)
df_mun['ano']              = df_mun['ano'].astype(str).str.strip()
df_mun['mes']              = df_mun['mes'].astype(str).str.strip().str.zfill(2)
df_mun['uf']               = df_mun['codigo_municipio'].str[:2].map(UF_POR_CODIGO)
df_mun['regiao']           = df_mun['uf'].map(REGIAO_POR_UF)

print(f"[DASH] Pronto — {len(df_mun)} registros carregados. Subindo servidor...", flush=True)

# ── Coordenadas dos municípios e Mapa de Calor ────────────────────────────────
import plotly.express as px

print("[DASH] Carregando coordenadas dos municípios...", flush=True)
COORDS_URL = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"
COORDS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "municipios_coords.csv")

try:
    os.makedirs(os.path.dirname(COORDS_CACHE), exist_ok=True)
    if os.path.exists(COORDS_CACHE):
        df_coords = pd.read_csv(COORDS_CACHE, dtype={'codigo_ibge': str})
    else:
        df_coords = pd.read_csv(COORDS_URL, dtype={'codigo_ibge': str})
        df_coords.to_csv(COORDS_CACHE, index=False)
    df_coords['cod6'] = df_coords['codigo_ibge'].str[:6]
    df_coords = df_coords[['cod6', 'latitude', 'longitude']].drop_duplicates(subset='cod6')
    print(f"[DASH] Coordenadas carregadas — {len(df_coords)} municípios", flush=True)
except Exception as e:
    print(f"[DASH] ERRO ao carregar coordenadas: {e}", flush=True)
    df_coords = pd.DataFrame(columns=['cod6', 'latitude', 'longitude'])

# Agregar total de casos por município (todas as doenças, todo o período)
print("[DASH] Montando mapa de calor...", flush=True)
_df_mapa = df_mun.groupby(['codigo_municipio', 'nome_municipio', 'uf'], as_index=False)['casos_mes'].sum()
_df_mapa = _df_mapa.rename(columns={'casos_mes': 'total_casos'})
_df_mapa['cod6'] = _df_mapa['codigo_municipio'].astype(str).str.strip()
_df_mapa = _df_mapa.merge(df_coords, on='cod6', how='inner')
_df_mapa = _df_mapa[_df_mapa['total_casos'] > 0].copy()

fig_mapa = px.density_mapbox(
    _df_mapa,
    lat="latitude",
    lon="longitude",
    z="total_casos",
    radius=12,
    zoom=3.3,
    center={"lat": -14.2, "lon": -51.9},
    mapbox_style="carto-positron",
    color_continuous_scale="YlOrRd",
    hover_name="nome_municipio",
    hover_data={"latitude": False, "longitude": False, "uf": True, "total_casos": ":,.0f", "cod6": False},
    labels={"total_casos": "Total de Casos", "uf": "UF"},
)
fig_mapa.update_layout(
    margin=dict(l=0, r=0, t=0, b=0),
    height=580,
    coloraxis_colorbar=dict(title="Casos", thickness=15, len=0.6),
)
del _df_mapa
print("[DASH] Mapa de calor pronto.", flush=True)

# ── App ───────────────────────────────────────────────────────────────────────
app    = dash.Dash(__name__, title="Doenças e Agravos — SINAN", suppress_callback_exceptions=True,
                  url_base_pathname=os.environ.get("DASH_PREFIX", "/doencas-agravos/"),
                  meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1.0"}],
                  assets_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"))
server = app.server

kpis = [_kpi(nomes_exibicao[row['doenca']], row['total_casos'], COR_POR_DOENCA[row['doenca']])
        for _, row in df_total.iterrows()]

app.layout = html.Div(
    style={"fontFamily": "Inter, sans-serif", "backgroundColor": COR_FUNDO, "minHeight": "100vh"},
    children=[
        # ── Header ────────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Img(src=app.get_asset_url("logo_funasa.png"), style={"height": "50px", "marginRight": "20px"}),
                html.Div([
                    html.P("FUNASA", style={"fontSize": 10, "color": "#8BAFC8",
                                            "margin": "0 0 2px 0", "letterSpacing": "0.1em", "fontWeight": 600}),
                    html.H1("Doenças e Agravos — Casos Notificados",
                            style={"fontSize": 22, "fontWeight": 700, "color": "#fff", "margin": 0}),
                    html.P("Total de casos notificados por doença (2007–2025) · Fonte: SINAN/DATASUS",
                           style={"fontSize": 12, "color": "#8BAFC8", "margin": "4px 0 0 0"}),
                ], id="header-titulo", style={"flex": 1}),
            ], style={"display": "flex", "alignItems": "center", "flex": 1}),
            html.Div([
                html.P(f"{len(doencas)}", style={"fontSize": 28, "fontWeight": 700,
                                                  "color": "#fff", "margin": 0, "textAlign": "center"}),
                html.P("DOENÇAS", style={"fontSize": 10, "color": "#8BAFC8", "margin": 0,
                                          "textAlign": "center", "letterSpacing": "0.05em"}),
            ], id="header-badge", style={"backgroundColor": "#2d4a6b", "borderRadius": 8, "padding": "12px 20px"}),
        ], id="header-container", style={"backgroundColor": COR_HEADER, "padding": "20px 32px",
                  "display": "flex", "alignItems": "center", "justifyContent": "space-between"}),

        # ── Conteúdo ──────────────────────────────────────────────────────────
        html.Div(id="conteudo-principal", style={"padding": "24px 32px"}, children=[

            html.P("Total de casos notificados por doença no período de 2007 a 2025",
                   style={"fontSize": 14, "fontWeight": 600, "color": "#2d3748", "marginBottom": 12}),

            html.Div(kpis, id="kpi-container", style={"display": "flex", "gap": 12, "marginBottom": 20, "flexWrap": "wrap"}),

            _card([
                _titulo("Total de Casos por Doença (2007–2025)"),
                dcc.Graph(figure=fig_barras, config={"displayModeBar": False}),
            ]),

            # ── Mapa de Calor por Município ───────────────────────────────────
            html.Div(style={"marginTop": 24}, children=[
                _card([
                    _titulo("Mapa de Calor — Concentração de Casos Notificados (2007–2025)"),

                    dcc.Graph(id="mapa-municipios",
                              figure=fig_mapa,
                              config={"displayModeBar": "hover", "scrollZoom": True,
                                      "displaylogo": False,
                                      "modeBarButtonsToRemove": ["toImage", "lasso2d", "select2d"]}),
                ]),
            ]),

            # ── Análise por Município ─────────────────────────────────────────
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
                                value="dengue", clearable=False,
                                style={"width": "180px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Região", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="filtro-regiao",
                                options=[{"label": "Todas", "value": "Todos"}] +
                                        [{"label": r, "value": r} for r in regioes],
                                value="Todos", clearable=False,
                                style={"width": "160px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("UF", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="filtro-uf",
                                options=[{"label": "Todas", "value": "Todos"}] +
                                        [{"label": uf, "value": uf} for uf in ufs],
                                value="Todos", clearable=False,
                                style={"width": "120px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Ano", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="filtro-ano",
                                options=[{"label": "Todos", "value": "Todos"}] +
                                        [{"label": a, "value": a} for a in anos],
                                value="Todos", clearable=False,
                                style={"width": "120px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Mês", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="filtro-mes",
                                options=[{"label": "Todos", "value": "Todos"}] +
                                        [{"label": NOME_MES[m], "value": m} for m in meses],
                                value="Todos", clearable=False,
                                style={"width": "140px", "fontSize": 13},
                            ),
                        ]),
                    ], id="filtros-container", style={"display": "flex", "gap": 16, "marginTop": 16,
                               "marginBottom": 20, "flexWrap": "wrap"}),

                    # Gráfico + Tabela
                    html.Div([
                        html.Div(id="grafico-top10", style={"flex": 1}),
                        html.Div([
                            html.Div(id="tabela-municipios",
                                     style={"maxHeight": "420px", "overflowY": "auto",
                                            "borderLeft": "1px solid #e2e8f0", "paddingLeft": "20px"}),
                            html.P(id="tabela-info",
                                   style={"fontSize": 11, "color": "#9ca3af", "margin": "8px 0 0 0"}),
                        ], style={"flex": 1, "paddingLeft": "20px"}),
                    ], id="grafico-tabela-container", style={"display": "flex", "gap": 20, "alignItems": "flex-start"}),
                ]),
            ]),
        ]),
    ]
)


# ── Callback: UF cascateia com região ────────────────────────────────────────
@app.callback(
    Output("filtro-uf", "options"),
    Output("filtro-uf", "value"),
    Input("filtro-regiao", "value"),
)
def atualizar_opcoes_uf(regiao_sel):
    if regiao_sel == "Todos":
        lista = ufs
    else:
        lista = sorted(UF_POR_REGIAO.get(regiao_sel, []))
    return [{"label": "Todas", "value": "Todos"}] + [{"label": u, "value": u} for u in lista], "Todos"


# ── Callback: Gráfico + Tabela — filtra em memória ───────────────────────────
@app.callback(
    Output("grafico-top10", "children"),
    Output("tabela-municipios", "children"),
    Output("tabela-info", "children"),
    Input("filtro-doenca", "value"),
    Input("filtro-regiao", "value"),
    Input("filtro-uf", "value"),
    Input("filtro-ano", "value"),
    Input("filtro-mes", "value"),
)
def atualizar_municipios(doenca_sel, regiao_sel, uf_sel, ano_sel, mes_sel):

    # ── Filtra em memória ─────────────────────────────────────────────
    df = df_mun[df_mun['doenca'] == doenca_sel].copy()

    if regiao_sel != "Todos":
        df = df[df['regiao'] == regiao_sel]
    if uf_sel != "Todos":
        df = df[df['uf'] == uf_sel]
    if ano_sel != "Todos":
        df = df[df['ano'] == ano_sel]
    if mes_sel != "Todos":
        df = df[df['mes'] == mes_sel]

    # Agrega por município (soma dos meses/anos filtrados)
    df = df.groupby(['codigo_municipio', 'nome_municipio', 'uf', 'regiao'], as_index=False)['casos_mes'].sum()
    df = df.rename(columns={'casos_mes': 'total_casos'})
    df = df.dropna(subset=['nome_municipio']).sort_values("total_casos", ascending=False)

    if df.empty:
        fig_vazio = go.Figure()
        fig_vazio.update_layout(
            plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
            xaxis={"visible": False}, yaxis={"visible": False},
            annotations=[{"text": "Nenhum dado encontrado", "showarrow": False,
                           "font": {"size": 14, "color": "#9ca3af"}}],
            height=380,
        )
        return dcc.Graph(figure=fig_vazio, config={"displayModeBar": False}), [], "0 municípios encontrados"

    # ── Gráfico top 10 ────────────────────────────────────────────────────
    top10 = df.head(10).sort_values("total_casos", ascending=True)
    fig = go.Figure(go.Bar(
        x=top10["total_casos"],
        y=top10["nome_municipio"] + " (" + top10["uf"].fillna("") + ")",
        orientation="h",
        marker_color=COR_POR_DOENCA[doenca_sel],
        hovertemplate="<b>%{y}</b><br>Casos: %{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
        font=dict(family="Inter, sans-serif", size=12, color="#333"),
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0", title="Total de Casos"),
        yaxis=dict(showgrid=False),
        height=380,
    )
    grafico = dcc.Graph(figure=fig, config={"displayModeBar": False})

    # ── Tabela HTML top 50 ────────────────────────────────────────────────
    top50 = df.head(50)
    th_style = {"padding": "10px 12px", "textAlign": "left", "fontSize": "11px",
                "fontWeight": "600", "color": "#4a5568", "borderBottom": "2px solid #e2e8f0",
                "textTransform": "uppercase", "letterSpacing": "0.03em", "backgroundColor": "#f7fafc"}
    header = html.Tr([html.Th(c, style=th_style) for c in ["Município", "UF", "Região", "Total de Casos"]])

    rows_html = []
    for i, (_, row) in enumerate(top50.iterrows()):
        bg = "#fafafa" if i % 2 == 1 else "#ffffff"
        td = {"padding": "7px 12px", "fontSize": "12px",
              "borderBottom": "1px solid #f0f0f0", "backgroundColor": bg}
        rows_html.append(html.Tr([
            html.Td(str(row.get("nome_municipio") or "—"), style=td),
            html.Td(str(row.get("uf") or "—"), style=td),
            html.Td(str(row.get("regiao") or "—"), style=td),
            html.Td(f"{row['total_casos']:,}".replace(",", "."),
                    style={**td, "fontWeight": "600", "textAlign": "right"}),
        ]))

    tabela = html.Table(
        [html.Thead(header), html.Tbody(rows_html)],
        style={"width": "100%", "borderCollapse": "collapse"}
    )

    total = len(df)
    info = f"Exibindo {min(50, total)} de {total} município(s) · ordenado por total de casos"
    return grafico, tabela, info


if __name__ == "__main__":
    app.run(debug=True, port=8050)
