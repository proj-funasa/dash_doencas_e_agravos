import os
import json
import math
import requests
import dash
from dash import dcc, html, Input, Output, Patch
import pandas as pd
import plotly.graph_objects as go
import trino
from trino.auth import BasicAuthentication

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TRINO_HOST = os.getenv("TRINO_HOST", "trino.trino.svc.cluster.local")
TRINO_PORT = int(os.getenv("TRINO_PORT", "8080"))
TRINO_USER = os.getenv("TRINO_USER", "funasa_reader")
TRINO_PASSWORD = os.getenv("TRINO_PASSWORD", "")

# ── Conexão Trino (interna k8s) ──────────────────────────────────────────────
def query(sql):
    """Abre conexão, executa query, retorna DataFrame e fecha."""
    kwargs = dict(host=TRINO_HOST, port=TRINO_PORT, user=TRINO_USER)
    if TRINO_PASSWORD:
        kwargs["http_scheme"] = "https"
        kwargs["auth"] = BasicAuthentication(TRINO_USER, TRINO_PASSWORD)
        kwargs["verify"] = False
    conn = trino.dbapi.connect(**kwargs)
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

# ── GeoJSON dos municípios (IBGE, qualidade mínima) e Mapa ────────────────────
import json

print("[DASH] Carregando GeoJSON de municípios (IBGE)...", flush=True)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
IBGE_GEOJSON_CACHE = os.path.join(CACHE_DIR, "ibge_municipios_minima.geojson")
IBGE_GEOJSON_URL = "https://servicodados.ibge.gov.br/api/v4/malhas/paises/BR"

try:
    os.makedirs(CACHE_DIR, exist_ok=True)
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
        with open(IBGE_GEOJSON_CACHE, "w", encoding="utf-8") as f:
            json.dump(geojson_municipios, f)
    geojson_ids = [str(feat["properties"].get("codarea", "")) for feat in geojson_municipios.get("features", [])]
    cod6_to_cod7 = {cod7[:6]: cod7 for cod7 in geojson_ids if len(cod7) >= 6}
    print(f"[DASH] GeoJSON carregado — {len(geojson_ids)} municípios", flush=True)
except Exception as e:
    print(f"[DASH] ERRO ao carregar GeoJSON: {e}. Mapa indisponível.", flush=True)
    geojson_municipios = {"type": "FeatureCollection", "features": []}
    geojson_ids = []
    cod6_to_cod7 = {}

# Carregar dados agregados para o mapa (tabela leve, sem ano/mês)
print("[DASH] Carregando dados para mapa...", flush=True)
df_mapa_raw = query("SELECT codigo_municipio, nome_municipio, doenca, total_casos FROM seaweedfs.gold.casos_por_municipio")
df_mapa_raw['codigo_municipio'] = df_mapa_raw['codigo_municipio'].astype(str).str.strip()
df_mapa_raw['nome_municipio'] = df_mapa_raw['nome_municipio'].str.title()
df_mapa_raw['total_casos'] = pd.to_numeric(df_mapa_raw['total_casos'], errors='coerce').fillna(0).astype(int)
df_mapa_raw['uf'] = df_mapa_raw['codigo_municipio'].str[:2].map(UF_POR_CODIGO)

# Pivotar para hover com todas as doenças
_pivot = df_mapa_raw.pivot_table(index=['codigo_municipio', 'nome_municipio', 'uf'],
                                  columns='doenca', values='total_casos', fill_value=0).reset_index()
_pivot.columns.name = None
for d in doencas:
    if d not in _pivot.columns:
        _pivot[d] = 0
_pivot['total_geral'] = _pivot[[d for d in doencas if d in _pivot.columns]].sum(axis=1)
_pivot = _pivot[_pivot['total_geral'] > 0].copy()
_pivot['cod7'] = _pivot['codigo_municipio'].map(cod6_to_cod7)
_pivot = _pivot.dropna(subset=['cod7'])
_ids_com_dados = set(_pivot['cod7'].tolist())

_z_values = [1 if loc in _ids_com_dados else 0 for loc in geojson_ids]

_hover_dict = {}
for _, row in _pivot.iterrows():
    linhas = [f"<b>{row['nome_municipio']}</b> ({row['uf']})"]
    for d in doencas:
        val = int(row.get(d, 0))
        if val > 0:
            linhas.append(f"{nomes_exibicao[d]}: <b>{val:,.0f}</b>".replace(",", "."))
    _hover_dict[row['cod7']] = "<br>".join(linhas)

_customdata = [_hover_dict.get(loc, "") for loc in geojson_ids]

FUNASA_MAP_STYLE = {
    "version": 8, "sources": {},
    "layers": [{"id": "background", "type": "background", "paint": {"background-color": "#E8F0F3"}}],
}

fig_mapa = go.Figure()
fig_mapa.add_trace(go.Choroplethmap(
    geojson=geojson_municipios,
    locations=geojson_ids,
    z=_z_values,
    featureidkey="properties.codarea",
    zmin=0, zmax=1,
    colorscale=[
        [0.0, "#F8FAFB"],
        [0.1, "#F8FAFB"],
        [0.11, "#BEE3F8"],
        [0.3, "#63B3ED"],
        [0.5, "#3182CE"],
        [0.7, "#2B6CB0"],
        [0.9, "#1A365D"],
        [0.91, "#C53030"],
        [1.0, "#C53030"],
    ],
    marker_opacity=0.95,
    marker_line_color="#8FA3B3",
    marker_line_width=0.5,
    customdata=_customdata,
    hovertemplate="%{customdata}<extra></extra>",
    showscale=False,
))
fig_mapa.update_layout(
    map=dict(style=FUNASA_MAP_STYLE, center={"lat": -14.2, "lon": -51.9}, zoom=3.3),
    margin=dict(l=0, r=0, t=0, b=0), height=580,
    paper_bgcolor="#E8F0F3", plot_bgcolor="#E8F0F3",
    dragmode="pan", hovermode="closest",
    hoverlabel=dict(bgcolor="#ffffff", bordercolor="#e2e8f0",
                    font=dict(family="Inter, sans-serif", size=12, color="#2d3748")),
    uirevision="mapa-doencas",
)

# Guardar dados para callback de busca (nome_lower -> lista de cod7s)
_mapa_busca_data = _pivot[['cod7', 'nome_municipio']].copy()
_mapa_busca_data['nome_lower'] = _mapa_busca_data['nome_municipio'].str.lower()
mapa_cod7_por_nome = {}
for _, r in _mapa_busca_data.iterrows():
    mapa_cod7_por_nome.setdefault(r['nome_lower'], []).append(r['cod7'])
# z base sem destaque
mapa_z_base = list(_z_values)

del _pivot, _ids_com_dados, _z_values, _hover_dict, _customdata, df_mapa_raw, _mapa_busca_data
print("[DASH] Mapa pronto.", flush=True)

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

            # ── Mapa por Município ─────────────────────────────────────────────
            html.Div(style={"marginTop": 24}, children=[
                _card([
                    _titulo("Mapa de Casos por Município"),

                    # Filtros do mapa
                    html.Div([
                        html.Div([
                            html.Label("Doenças", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="mapa-filtro-doenca",
                                options=[{"label": nomes_exibicao[d], "value": d} for d in doencas],
                                value=[],
                                multi=True,
                                placeholder="Todas as doenças",
                                style={"width": "320px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Ano Início", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="mapa-filtro-ano-inicio",
                                options=[{"label": a, "value": a} for a in anos],
                                value=anos[0], clearable=False,
                                style={"width": "100px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Ano Fim", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Dropdown(
                                id="mapa-filtro-ano-fim",
                                options=[{"label": a, "value": a} for a in anos],
                                value=anos[-1], clearable=False,
                                style={"width": "100px", "fontSize": 13},
                            ),
                        ]),
                        html.Div([
                            html.Label("Buscar município", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568"}),
                            dcc.Input(
                                id="mapa-busca-municipio",
                                type="text",
                                placeholder="Digite o nome...",
                                debounce=True,
                                style={"width": "220px", "fontSize": 13, "padding": "6px 12px",
                                       "border": "1px solid #e2e8f0", "borderRadius": 6},
                            ),
                        ]),
                    ], id="mapa-filtros-container", style={"display": "flex", "gap": 16, "marginTop": 12,
                               "marginBottom": 8, "flexWrap": "wrap", "alignItems": "flex-end"}),

                    dcc.Graph(id="mapa-municipios",
                              figure=fig_mapa,
                              config={"displayModeBar": "hover", "scrollZoom": True,
                                      "displaylogo": False,
                                      "modeBarButtonsToRemove": ["toImage", "lasso2d", "select2d"]}),
                ]),
            ]),

            # ── Gráfico de evolução ao clicar no município ────────────────────
            html.Div(id="grafico-clique-municipio-container", style={"marginTop": 24}),

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


# ── Callback: Mapa com filtro de doença, ano e busca ──────────────────────────
@app.callback(
    Output("mapa-municipios", "figure"),
    Input("mapa-filtro-doenca", "value"),
    Input("mapa-filtro-ano-inicio", "value"),
    Input("mapa-filtro-ano-fim", "value"),
    Input("mapa-busca-municipio", "value"),
)
def atualizar_mapa(doencas_sel, ano_inicio, ano_fim, busca):
    # Filtrar df_mun conforme seleção
    df = df_mun.copy()
    if doencas_sel and len(doencas_sel) > 0:
        df = df[df['doenca'].isin(doencas_sel)]
    # Filtrar por intervalo de anos
    if ano_inicio and ano_fim:
        a_ini = str(min(int(ano_inicio), int(ano_fim)))
        a_fim = str(max(int(ano_inicio), int(ano_fim)))
        df = df[(df['ano'] >= a_ini) & (df['ano'] <= a_fim)]

    # Agregar por município
    df_agg = df.groupby('codigo_municipio', as_index=False)['casos_mes'].sum()
    df_agg = df_agg.rename(columns={'casos_mes': 'total_casos'})

    # Mapear cod6 -> total para z (proporcional à quantidade de casos)
    cod6_totais = dict(zip(df_agg['codigo_municipio'], df_agg['total_casos']))

    # Calcular z proporcional: 0=sem dados, 0.1-0.9=gradiente por casos, 1.0=destaque busca
    max_casos = df_agg['total_casos'].max() if not df_agg.empty else 1
    if max_casos == 0:
        max_casos = 1

    z_novo = []
    for cod7 in geojson_ids:
        cod6 = cod7[:6]
        total = cod6_totais.get(cod6, 0)
        if total > 0:
            # Escala de 0.11 a 0.9 (proporcional ao log dos casos para melhor distribuição)
            ratio = math.log1p(total) / math.log1p(max_casos)
            z_novo.append(0.11 + ratio * 0.79)
        else:
            z_novo.append(0)

    # Busca por nome (destaque = 1.0 = vermelho)
    if busca and busca.strip():
        termo = busca.strip().lower()
        cod7s_match = set()
        for nome, cod7_list in mapa_cod7_por_nome.items():
            if termo in nome:
                cod7s_match.update(cod7_list)
        if cod7s_match:
            z_novo = [1.0 if loc in cod7s_match else z_novo[i] for i, loc in enumerate(geojson_ids)]

    # Rebuild hover com dados filtrados — detalhado por doença
    nomes_mun = df_mun[['codigo_municipio', 'nome_municipio', 'uf']].drop_duplicates('codigo_municipio')
    nomes_dict = dict(zip(nomes_mun['codigo_municipio'], nomes_mun[['nome_municipio', 'uf']].values.tolist()))

    # Agregar por municipio E doença para hover detalhado
    df_hover = df.groupby(['codigo_municipio', 'doenca'], as_index=False)['casos_mes'].sum()
    hover_por_mun = {}
    for _, row in df_hover.iterrows():
        cod = row['codigo_municipio']
        if cod not in hover_por_mun:
            hover_por_mun[cod] = {}
        hover_por_mun[cod][row['doenca']] = int(row['casos_mes'])

    customdata_novo = []
    for cod7 in geojson_ids:
        cod6 = cod7[:6]
        total = cod6_totais.get(cod6, 0)
        info = nomes_dict.get(cod6, None)
        if info and total > 0:
            nome, uf = info
            linhas = [f"<b>{nome}</b> ({uf})"]
            doencas_mun = hover_por_mun.get(cod6, {})
            for d in doencas:
                val = doencas_mun.get(d, 0)
                if val > 0:
                    linhas.append(f"{nomes_exibicao[d]}: <b>{val:,.0f}</b>".replace(",", "."))
            customdata_novo.append("<br>".join(linhas))
        else:
            customdata_novo.append("")

    patched = Patch()
    patched["data"][0]["z"] = z_novo
    patched["data"][0]["customdata"] = customdata_novo
    return patched


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


# ── Callback: Clique no mapa → gráfico de linhas por doença ──────────────────
@app.callback(
    Output("grafico-clique-municipio-container", "children"),
    Input("mapa-municipios", "clickData"),
    Input("mapa-filtro-doenca", "value"),
    Input("mapa-filtro-ano-inicio", "value"),
    Input("mapa-filtro-ano-fim", "value"),
)
def grafico_clique_municipio(click_data, doencas_sel, ano_inicio, ano_fim):
    if not click_data:
        return html.P("Clique em um município no mapa para ver a evolução por doença.",
                      style={"fontSize": 13, "color": "#718096", "fontStyle": "italic", "padding": "20px"})

    # Extrair cod7 do ponto clicado
    try:
        point = click_data["points"][0]
        idx = point.get("pointIndex", point.get("pointNumber", None))
        if idx is None:
            return html.P("Não foi possível identificar o município.", style={"fontSize": 13, "color": "#C53030"})
        cod7 = geojson_ids[idx]
        cod6 = cod7[:6]
    except (KeyError, IndexError, TypeError):
        return html.P("Não foi possível identificar o município.", style={"fontSize": 13, "color": "#C53030"})

    # Filtrar dados do município
    df_local = df_mun[df_mun['codigo_municipio'] == cod6].copy()
    if df_local.empty:
        return html.P("Sem dados para este município.", style={"fontSize": 13, "color": "#C53030"})

    # Aplicar filtro de doenças (acompanha o filtro do mapa)
    if doencas_sel and len(doencas_sel) > 0:
        df_local = df_local[df_local['doenca'].isin(doencas_sel)]

    # Aplicar filtro de intervalo de anos (acompanha o filtro do mapa)
    if ano_inicio and ano_fim:
        a_ini = str(min(int(ano_inicio), int(ano_fim)))
        a_fim = str(max(int(ano_inicio), int(ano_fim)))
        df_local = df_local[(df_local['ano'] >= a_ini) & (df_local['ano'] <= a_fim)]

    if df_local.empty:
        return html.P("Sem dados para este município no período/doenças selecionados.",
                      style={"fontSize": 13, "color": "#C53030"})

    nome_mun = df_local['nome_municipio'].iloc[0]
    uf_mun = df_local['uf'].iloc[0]

    # Agregar por ano e doença (ou por mês se ano único)
    ano_unico = (ano_inicio and ano_fim and str(ano_inicio) == str(ano_fim))

    if ano_unico:
        # Mostrar por mês
        df_local['mes_int'] = df_local['mes'].astype(int)
        df_ano_doenca = df_local.groupby(['mes_int', 'doenca'], as_index=False)['casos_mes'].sum()
        df_ano_doenca = df_ano_doenca.rename(columns={'casos_mes': 'casos'})
        df_ano_doenca = df_ano_doenca.sort_values('mes_int')
        eixo_x = 'mes_int'
        nomes_meses = {1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
                       7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'}
    else:
        df_ano_doenca = df_local.groupby(['ano', 'doenca'], as_index=False)['casos_mes'].sum()
        df_ano_doenca = df_ano_doenca.rename(columns={'casos_mes': 'casos'})
        df_ano_doenca['ano'] = df_ano_doenca['ano'].astype(int)
        df_ano_doenca = df_ano_doenca.sort_values('ano')
        eixo_x = 'ano'

    # Gráfico de linhas — uma linha por doença
    fig = go.Figure()
    doencas_presentes = df_ano_doenca['doenca'].unique()
    for d in doencas:
        if d not in doencas_presentes:
            continue
        dados_d = df_ano_doenca[df_ano_doenca['doenca'] == d]
        if dados_d['casos'].sum() == 0:
            continue
        if ano_unico:
            x_vals = dados_d['mes_int']
            hover_tpl = f"<b>{nomes_exibicao[d]}</b><br>%{{text}}: %{{y:,.0f}} casos<extra></extra>"
            text_vals = [nomes_meses.get(m, str(m)) for m in dados_d['mes_int']]
        else:
            x_vals = dados_d['ano']
            hover_tpl = f"<b>{nomes_exibicao[d]}</b><br>%{{x}}: %{{y:,.0f}} casos<extra></extra>"
            text_vals = None

        trace_kwargs = dict(
            x=x_vals,
            y=dados_d['casos'],
            name=nomes_exibicao[d],
            mode="lines+markers",
            line=dict(color=COR_POR_DOENCA[d], width=2),
            marker=dict(size=5),
            hovertemplate=hover_tpl,
        )
        if text_vals:
            trace_kwargs['text'] = text_vals
        fig.add_trace(go.Scatter(**trace_kwargs))

    # Configurar eixo X
    if ano_unico:
        xaxis_config = dict(showgrid=False, linecolor="#e0e0e0", dtick=1,
                            tickvals=list(range(1, 13)),
                            ticktext=[nomes_meses[m] for m in range(1, 13)],
                            title=f"Meses de {ano_inicio}")
    else:
        xaxis_config = dict(showgrid=False, linecolor="#e0e0e0", dtick=1, tickformat="d")

    fig.update_layout(
        margin=dict(l=40, r=20, t=10, b=40),
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
        font=dict(family="Inter, sans-serif", size=12, color="#333"),
        xaxis=xaxis_config,
        yaxis=dict(gridcolor="#f0f0f0", linecolor="#e0e0e0", title="Casos"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font_size=11),
        height=400,
        hoverlabel=dict(bgcolor="#fff", bordercolor="#ccc", font_size=12),
    )

    return _card([
        _titulo(f"{nome_mun} ({uf_mun}) — Evolução de Casos por Doença"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


if __name__ == "__main__":
    app.run(debug=True, port=8050)
