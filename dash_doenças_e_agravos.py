import os
import copy
import dash
from dash import dcc, html, Input, Output
import branca.colormap as cm
import folium
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
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

# ── Carregar dados do Gold na inicialização ───────────────────────────────────
print("[DASH] Carregando KPIs...", flush=True)
df_total = query("SELECT doenca, total_casos FROM seaweedfs.gold.kpi_total_por_doenca")
df_total['total_casos'] = pd.to_numeric(df_total['total_casos'], errors='coerce').fillna(0).astype(int)
df_total = df_total.set_index('doenca').reindex(doencas).reset_index()

print("[DASH] Carregando municípios (sem ano)...", flush=True)
df_mun = query("SELECT codigo_municipio, nome_municipio, doenca, total_casos FROM seaweedfs.gold.casos_por_municipio")
df_mun['codigo_municipio'] = df_mun['codigo_municipio'].astype(str).str.strip()
df_mun['nome_municipio']   = df_mun['nome_municipio'].str.title()
df_mun['total_casos']      = pd.to_numeric(df_mun['total_casos'], errors='coerce').fillna(0).astype(int)
df_mun['uf']               = df_mun['codigo_municipio'].str[:2].map(UF_POR_CODIGO)
df_mun['regiao']           = df_mun['uf'].map(REGIAO_POR_UF)

print(f"[DASH] Pronto — {len(df_mun)} municípios carregados. Subindo servidor...", flush=True)

# ── Preparar dados agregados por UF (para o mapa coroplético) ─────────────────
df_uf_doenca = df_mun.groupby(['uf', 'doenca'], as_index=False)['total_casos'].sum()

# ── Carregar GeoJSON dos estados do Brasil ────────────────────────────────────
print("[DASH] Carregando GeoJSON dos estados...", flush=True)
GEOJSON_URL = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
_geojson_response = requests.get(GEOJSON_URL)
GEOJSON_ESTADOS = _geojson_response.json()

# Calcula bounds do Brasil a partir do GeoJSON
_all_coords = []
for _feature in GEOJSON_ESTADOS["features"]:
    _geom = _feature["geometry"]
    if _geom["type"] == "Polygon":
        for _ring in _geom["coordinates"]:
            _all_coords.extend(_ring)
    elif _geom["type"] == "MultiPolygon":
        for _polygon in _geom["coordinates"]:
            for _ring in _polygon:
                _all_coords.extend(_ring)
BOUNDS_BRASIL = [[min(c[1] for c in _all_coords), min(c[0] for c in _all_coords)],
                 [max(c[1] for c in _all_coords), max(c[0] for c in _all_coords)]]


# ── Função para gerar o mapa Folium por doença ───────────────────────────────
def gerar_mapa_uf(doenca_sel):
    """Gera HTML de mapa coroplético por UF para uma doença específica."""
    dados = df_uf_doenca[df_uf_doenca['doenca'] == doenca_sel].copy()
    dados_dict = dados.set_index('uf')['total_casos'].to_dict()

    # Cópia do GeoJSON para injetar propriedades
    geojson = copy.deepcopy(GEOJSON_ESTADOS)

    for feature in geojson["features"]:
        sigla = feature["properties"]["sigla"]
        casos = dados_dict.get(sigla, 0)
        feature["properties"]["total_casos"] = f"{casos:,.0f}".replace(",", ".")
        feature["properties"]["total_casos_raw"] = casos

    # Valores para a escala
    valores = [dados_dict.get(uf, 0) for uf in REGIAO_POR_UF.keys()]
    vmin = 0
    vmax = max(valores) if max(valores) > 0 else 1

    # Paleta sequencial (branco → laranja → vermelho escuro)
    colormap = cm.LinearColormap(
        colors=["#FFF5F0", "#FEE0D2", "#FCBBA1", "#FC9272", "#FB6A4A", "#DE2D26", "#A50F15"],
        vmin=vmin,
        vmax=vmax,
        caption=f"Total de Casos — {nomes_exibicao[doenca_sel]} (2007–2025)",
    )

    # Mapa sem tiles (fundo branco, apenas Brasil)
    m = folium.Map(
        location=[-14.2350, -51.9253],
        zoom_start=4,
        tiles=None,
        zoom_control=False,
    )
    m.fit_bounds(BOUNDS_BRASIL, padding=[10, 10])
    colormap.add_to(m)

    def style_function(feature):
        sigla = feature["properties"]["sigla"]
        valor = dados_dict.get(sigla, 0)
        return {
            "fillColor": colormap(valor),
            "fillOpacity": 0.82,
            "weight": 1.5,
            "color": "#ffffff",
            "opacity": 1,
        }

    # Borda externa do Brasil
    folium.GeoJson(
        geojson,
        style_function=lambda x: {
            "fillOpacity": 0,
            "weight": 2.5,
            "color": "#cbd5e0",
            "opacity": 0.8,
        },
        name="contorno_brasil",
    ).add_to(m)

    # Camada principal + tooltip
    folium.GeoJson(
        geojson,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=["name", "sigla", "total_casos"],
            aliases=["Estado:", "UF:", "Total de Casos:"],
            localize=True,
            sticky=True,
            style="""
                background-color: #ffffff;
                border: none;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                color: #2d3748;
                font-family: 'Inter', sans-serif;
                font-size: 13px;
                padding: 12px 16px;
                line-height: 1.6;
            """,
        ),
        highlight_function=lambda x: {
            "weight": 2.5,
            "color": "#2d3748",
            "fillOpacity": 0.9,
        },
    ).add_to(m)

    # Injeta CSS para fundo branco e layout responsivo
    map_html = m._repr_html_()
    inject_css = """
    <style>
        html, body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            height: 100% !important;
            overflow: hidden;
            background-color: #ffffff;
        }
        .folium-map {
            position: absolute !important;
            top: 20px !important;
            left: 20px !important;
            width: calc(100% - 40px) !important;
            height: calc(100% - 40px) !important;
            background-color: #ffffff !important;
        }
        #map, [id^="map_"] {
            width: 100% !important;
            height: 100% !important;
            background-color: #ffffff !important;
        }
        .leaflet-container {
            background-color: #ffffff !important;
        }
        .legend {
            background: white !important;
            border-radius: 6px !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.12) !important;
            padding: 8px 12px !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 11px !important;
        }
        .caption {
            font-family: 'Inter', sans-serif !important;
            font-size: 11px !important;
            font-weight: 600 !important;
            color: #4a5568 !important;
        }
        @media (max-width: 600px) {
            .legend {
                transform: scale(0.65) !important;
                transform-origin: bottom left !important;
            }
        }
    </style>
    """
    map_html = map_html.replace('</head>', inject_css + '</head>')
    return map_html


# Pré-gerar mapa padrão (dengue) para carregamento inicial
print("[DASH] Gerando mapa inicial (dengue)...", flush=True)
mapa_inicial_html = gerar_mapa_uf("dengue")

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

            # ── Mapa Coroplético por UF ───────────────────────────────────────
            html.Div(style={"marginTop": 24}, children=[
                html.Div(style={
                    "backgroundColor": "#ffffff", "borderRadius": 8,
                    "padding": "20px 24px", "boxShadow": "0 2px 8px rgba(0,0,0,0.12)",
                }, children=[
                    html.Div([
                        _titulo("Mapa de Casos Notificados por UF"),
                        html.Div([
                            html.Label("Doença", style={"fontSize": 11, "fontWeight": 600, "color": "#4a5568", "marginRight": 8}),
                            dcc.Dropdown(
                                id="filtro-doenca-mapa",
                                options=[{"label": nomes_exibicao[d], "value": d} for d in doencas],
                                value="dengue", clearable=False,
                                style={"width": "180px", "fontSize": 13},
                            ),
                        ], style={"display": "flex", "alignItems": "center"}),
                    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": 12}),
                    html.Iframe(
                        id="mapa-uf-iframe",
                        srcDoc=mapa_inicial_html,
                        style={"width": "100%", "height": "500px", "border": "none", "borderRadius": "8px"},
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


# ── Callback: Atualiza mapa coroplético por UF ──────────────────────────────
@app.callback(
    Output("mapa-uf-iframe", "srcDoc"),
    Input("filtro-doenca-mapa", "value"),
)
def atualizar_mapa_uf(doenca_sel):
    return gerar_mapa_uf(doenca_sel)


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


# ── Callback: Gráfico + Tabela — filtra em memória (sem filtro de ano) ────────
@app.callback(
    Output("grafico-top10", "children"),
    Output("tabela-municipios", "children"),
    Output("tabela-info", "children"),
    Input("filtro-doenca", "value"),
    Input("filtro-regiao", "value"),
    Input("filtro-uf", "value"),
)
def atualizar_municipios(doenca_sel, regiao_sel, uf_sel):

    # ── Filtra em memória — dados totais sem recorte de ano ───────────
    df = df_mun[df_mun['doenca'] == doenca_sel].copy()

    if regiao_sel != "Todos":
        df = df[df['regiao'] == regiao_sel]
    if uf_sel != "Todos":
        df = df[df['uf'] == uf_sel]

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