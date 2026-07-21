import os
import json
import requests
import dash
from dash import dcc, html, Input, Output, Patch
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

# ── GeoJSON dos municípios (IBGE, qualidade mínima) ───────────────────────────
print("[DASH] Carregando GeoJSON de municípios (IBGE)...", flush=True)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
IBGE_GEOJSON_CACHE = os.path.join(CACHE_DIR, "ibge_municipios_minima.geojson")
IBGE_GEOJSON_URL = "https://servicodados.ibge.gov.br/api/v4/malhas/paises/BR"

try:
    if os.path.exists(IBGE_GEOJSON_CACHE):
        with open(IBGE_GEOJSON_CACHE, encoding="utf-8") as f:
            geojson_municipios = json.load(f)
    else:
        resp = requests.get(
            IBGE_GEOJSON_URL,
            params={"intrarregiao": "municipio", "formato": "application/vnd.geo+json", "qualidade": "minima"},
            timeout=120,
        )
        resp.raise_for_status()
        geojson_municipios = resp.json()
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(IBGE_GEOJSON_CACHE, "w", encoding="utf-8") as f:
            json.dump(geojson_municipios, f)
    # Extrair lista de IDs para o mapa
    geojson_ids = [str(feat["properties"].get("codarea", "")) for feat in geojson_municipios.get("features", [])]
    # Mapa de cod6 (sem dígito verificador) -> cod7 (com dígito verificador)
    cod6_to_cod7 = {cod7[:6]: cod7 for cod7 in geojson_ids if len(cod7) >= 6}
    print(f"[DASH] GeoJSON carregado — {len(geojson_ids)} municípios", flush=True)
except Exception as e:
    print(f"[DASH] ERRO ao carregar GeoJSON: {e}. Mapa ficará indisponível.", flush=True)
    geojson_municipios = {"type": "FeatureCollection", "features": []}
    geojson_ids = []

# Estilo do mapa (igual ao Painel Municípios)
FUNASA_MAP_STYLE = {
    "version": 8,
    "sources": {},
    "layers": [{"id": "background", "type": "background", "paint": {"background-color": "#E8F0F3"}}],
}

# ── Cores ─────────────────────────────────────────────────────────────────────
COR_HEADER = "#1B3A5C"
COR_FUNDO  = "#F0F2F5"
CORES_DOENCAS = [
    "#2B6CB0", "#2F855A", "#D85A30", "#7F77DD", "#1D9E75",
    "#EF9F27", "#378ADD", "#C53030", "#5A6B7A", "#9F7AEA", "#DD6B20"
]
COR_POR_DOENCA = {d: CORES_DOENCAS[i] for i, d in enumerate(doencas)}


# ── Helpers de layout ─────────────────────────────────────────────────────────
def _kpi(nome, valor, cor):
    return html.Div([
        html.P(f"{valor:,.0f}".replace(",", "."),
               style={"fontSize": 26, "fontWeight": 700, "color": "#fff", "margin": "0 0 4px 0"}),
        html.P(nome, style={"fontSize": 11, "fontWeight": 600, "color": "#fff", "margin": 0,
                            "textTransform": "uppercase", "letterSpacing": "0.05em"}),
    ], style={"backgroundColor": cor, "borderRadius": 8,
              "padding": "18px 22px", "flex": 1, "minWidth": "200px"})


def _card(children):
    return html.Div(children, style={
        "backgroundColor": "#ffffff", "borderRadius": 8,
        "padding": "20px 24px", "border": "1px solid #e2e8f0", "flex": 1
    })


def _titulo(texto):
    return html.P(texto, style={"fontSize": 13, "fontWeight": 600, "color": "#2d3748", "margin": 0})


# ── Gráfico de barras (KPIs) ──────────────────────────────────────────────────
df_sorted  = df_total.sort_values("total_casos", ascending=True)
fig_barras = go.Figure(go.Bar(
    x=df_sorted["total_casos"],
    y=[nomes_exibicao[d] for d in df_sorted["doenca"]],
    orientation="h",
    marker_color=[COR_POR_DOENCA[d] for d in df_sorted["doenca"]],
    hovertemplate="<b>%{y}</b><br>Casos: %{x:,.0f}<extra></extra>",
))
fig_barras.update_layout(
    margin=dict(l=10, r=20, t=10, b=40),
    plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
    font=dict(family="Inter, sans-serif", size=12, color="#333"),
    xaxis=dict(showgrid=True, gridcolor="#f0f0f0", linecolor="#e0e0e0", title="Total de Casos"),
    yaxis=dict(showgrid=False, linecolor="#e0e0e0"),
    hoverlabel=dict(bgcolor="#fff", bordercolor="#ccc", font_size=12),
    height=420,
)

# ── Figura inicial do Mapa ────────────────────────────────────────────────────
fig_mapa_inicial = go.Figure()
fig_mapa_inicial.add_trace(go.Choroplethmap(
    geojson=geojson_municipios,
    locations=geojson_ids,
    z=[0] * len(geojson_ids),
    featureidkey="properties.codarea",
    zmin=0, zmax=1,
    colorscale=[[0, "#F8FAFB"], [0.4999, "#F8FAFB"], [0.5, "#DCECF5"], [1, "#DCECF5"]],
    marker_opacity=0.95,
    marker_line_color="#C5D1D9",
    marker_line_width=0.35,
    customdata=[""] * len(geojson_ids),
    hovertemplate="%{customdata}<extra></extra>",
    showscale=False,
))
fig_mapa_inicial.update_layout(
    map=dict(style=FUNASA_MAP_STYLE, center={"lat": -14.2, "lon": -51.9}, zoom=3.3),
    margin=dict(l=0, r=0, t=0, b=0), height=580,
    paper_bgcolor="#E8F0F3", plot_bgcolor="#E8F0F3",
    dragmode="pan", hovermode="closest",
    hoverlabel=dict(bgcolor="#ffffff", bordercolor="#e2e8f0",
                    font=dict(family="Inter, sans-serif", size=12, color="#2d3748")),
    uirevision="mapa-doencas",
)

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

            # ── Mapa Coroplético por Município ────────────────────────────────
            html.Div(style={"marginTop": 24}, children=[
                _card([
                    _titulo("Mapa de Casos por Município"),

                    # Filtros do mapa
                    html.Div([
                        html.Div([
                            html.Label("Doença", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="mapa-filtro-doenca",
                                options=[{"label": nomes_exibicao[d], "value": d} for d in doencas],
                                value="dengue", clearable=False,
                                style={"width": "180px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Ano", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="mapa-filtro-ano",
                                options=[{"label": "Todos", "value": "Todos"}] +
                                        [{"label": a, "value": a} for a in anos],
                                value="Todos", clearable=False,
                                style={"width": "120px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Mês", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="mapa-filtro-mes",
                                options=[{"label": "Todos", "value": "Todos"}] +
                                        [{"label": NOME_MES[m], "value": m} for m in meses],
                                value="Todos", clearable=False,
                                style={"width": "140px", "fontSize": 13},
                            ),
                        ]),
                    ], style={"display": "flex", "gap": 16, "marginTop": 16, "marginBottom": 16, "flexWrap": "wrap"}),

                    dcc.Loading(
                        dcc.Graph(id="mapa-municipios",
                                  figure=fig_mapa_inicial,
                                  config={"displayModeBar": "hover", "scrollZoom": True,
                                          "displaylogo": False,
                                          "modeBarButtonsToRemove": ["toImage", "lasso2d", "select2d"]}),
                        type="circle",
                    ),
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


# ── Callback: Mapa de casos por município ─────────────────────────────────────
@app.callback(
    Output("mapa-municipios", "figure"),
    Input("mapa-filtro-doenca", "value"),
    Input("mapa-filtro-ano", "value"),
    Input("mapa-filtro-mes", "value"),
)
def atualizar_mapa(doenca_sel, ano_sel, mes_sel):
    # Filtrar por período
    df_filtrado = df_mun.copy()
    if ano_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado['ano'] == ano_sel]
    if mes_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado['mes'] == mes_sel]

    # Agregar TODAS as doenças por município
    df_filtrado['cod6'] = df_filtrado['codigo_municipio'].astype(str).str.strip()
    df_agg = df_filtrado.groupby(['cod6', 'nome_municipio', 'uf', 'doenca'], as_index=False)['casos_mes'].sum()

    # Pivotar para ter uma coluna por doença
    df_pivot = df_agg.pivot_table(
        index=['cod6', 'nome_municipio', 'uf'],
        columns='doenca', values='casos_mes', fill_value=0
    ).reset_index()
    df_pivot.columns.name = None

    for d in doencas:
        if d not in df_pivot.columns:
            df_pivot[d] = 0

    # Doença selecionada define quais municípios ficam destacados
    df_pivot['casos_sel'] = df_pivot[doenca_sel]
    df_com_dados = df_pivot[df_pivot['casos_sel'] > 0].copy()

    # Mapear cod6 -> cod7 para compatibilizar com GeoJSON do IBGE
    df_com_dados['cod7'] = df_com_dados['cod6'].map(cod6_to_cod7)
    df_com_dados = df_com_dados.dropna(subset=['cod7'])
    ids_com_dados = set(df_com_dados['cod7'].tolist())

    # Montar z e customdata
    z_values = [1 if loc in ids_com_dados else 0 for loc in geojson_ids]

    hover_dict = {}
    for _, row in df_com_dados.iterrows():
        linhas = [f"<b>{row['nome_municipio']}</b> ({row['uf']})"]
        for d in doencas:
            val = int(row.get(d, 0))
            if val > 0:
                marcador = " ◀" if d == doenca_sel else ""
                linhas.append(f"{nomes_exibicao[d]}: <b>{val:,.0f}</b>{marcador}".replace(",", "."))
        hover_dict[row['cod7']] = "<br>".join(linhas)

    customdata = [hover_dict.get(loc, "") for loc in geojson_ids]

    # Usar Patch para atualizar apenas z e customdata (sem reenviar GeoJSON)
    patched = Patch()
    patched["data"][0]["z"] = z_values
    patched["data"][0]["customdata"] = customdata
    return patched


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
