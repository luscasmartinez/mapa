from pathlib import Path

import pandas as pd
import pydeck as pdk
import pyrebase
import streamlit as st

st.set_page_config(page_title="Mapa de Ligações", layout="wide")

# Configuração Firebase
firebase_config = st.secrets["firebase"]

firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()

# Verificação de login
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("Login")
    email = st.text_input("Email")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state.logged_in = True
            st.session_state.user = user
            st.rerun()
        except Exception as e:
            st.error(f"Erro no login: {str(e)}")
    st.stop()

# Código do app principal

ARQUIVO = Path(__file__).resolve().parent / "dados_mapa.parquet"

@st.cache_data(show_spinner="Carregando dados…")
def carregar_dados():
    df = pd.read_parquet(ARQUIVO)

    # cor base por regra de negócio
    def classificar_tipo(tipo, gc):
        tipo = str(tipo).upper()

        if gc == "SIM":
            return "GC"

        if "AGUA" in tipo and "ESGOTO" in tipo and "T.E.E" in tipo:
            return "AGUA_ESGOTO_TEE"
        elif "AGUA" in tipo and "ESGOTO" in tipo:
            return "AGUA_ESGOTO"
        elif "AGUA" in tipo and "T.E.E" in tipo:
            return "AGUA_TEE"
        elif "T.E.E" in tipo:
            return "TEE"
        elif "AGUA" in tipo:
            return "AGUA"
        else:
            return "OUTROS"

    df["CLASSE_MAPA"] = df.apply(
        lambda row: classificar_tipo(row["TIPO_FATURAMENTO"], row["GC"]),
        axis=1
    )

    mapa_cores = {
        "AGUA": [255, 0, 0, 180],                 # vermelho
        "AGUA_ESGOTO": [0, 128, 0, 180],          # verde
        "TEE": [139, 69, 19, 180],                # marrom
        "AGUA_TEE": [255, 165, 0, 180],           # laranja
        "AGUA_ESGOTO_TEE": [0, 0, 255, 180],      # azul
        "GC": [212, 175, 55, 220],                # dourado
        "OUTROS": [128, 128, 128, 150]            # cinza
    }

    df["cor"] = df["CLASSE_MAPA"].map(mapa_cores)

    # Evita chaves com espaços/símbolos em tooltip e seleção de colunas
    if "NOM_BAIRRO - CIDADE" in df.columns and "NOM_BAIRRO_CIDADE" not in df.columns:
        df["NOM_BAIRRO_CIDADE"] = df["NOM_BAIRRO - CIDADE"]

    return df

df = carregar_dados()

st.title("Mapa Profissional de Ligações")

with st.sidebar:
    st.header("Filtros")

    cidades = sorted(df["CIDADE"].dropna().unique().tolist())
    cidade = st.selectbox("Cidade", ["TODAS"] + cidades)

    classes = sorted(df["CLASSE_MAPA"].dropna().unique().tolist())
    classes_sel = st.multiselect("Tipo de faturamento", classes, default=classes)

    gc_sel = st.radio("GC", ["TODOS", "SIM", "NAO"], index=0)

    modo = st.radio("Visualização", ["PONTOS", "DENSIDADE"], index=0)

    max_pontos = st.slider("Máximo de pontos renderizados", 1000, 100000, 30000, step=1000)

df_filtrado = df.copy()

if cidade != "TODAS":
    df_filtrado = df_filtrado[df_filtrado["CIDADE"] == cidade]

if classes_sel:
    df_filtrado = df_filtrado[df_filtrado["CLASSE_MAPA"].isin(classes_sel)]

if gc_sel == "SIM":
    df_filtrado = df_filtrado[df_filtrado["GC"] == "SIM"]
elif gc_sel == "NAO":
    df_filtrado = df_filtrado[df_filtrado["GC"] != "SIM"]

total_filtrado = len(df_filtrado)

# proteção de performance
if len(df_filtrado) > max_pontos:
    df_mapa = df_filtrado.sample(max_pontos, random_state=42)
else:
    df_mapa = df_filtrado.copy()

st.write(f"*Registros filtrados:* {total_filtrado:,}")
st.write(f"*Registros renderizados no mapa:* {len(df_mapa):,}")

if len(df_mapa) == 0:
    st.warning("Nenhum ponto encontrado com os filtros atuais.")
    st.stop()

lat_centro = df_mapa["COD_LATITUDE"].mean()
lon_centro = df_mapa["COD_LONGITUDE"].mean()

view_state = pdk.ViewState(
    latitude=float(lat_centro),
    longitude=float(lon_centro),
    zoom=11 if cidade != "TODAS" else 6,
    pitch=0
)

tooltip = {
    "html": """
    <b>Ligação:</b> {NUM_LIGACAO}<br/>
    <b>Cidade:</b> {CIDADE}<br/>
    <b>Bairro:</b> {NOM_BAIRRO_CIDADE}<br/>
    <b>Tipo:</b> {TIPO_FATURAMENTO}<br/>
    <b>GC:</b> {GC}
    """,
    "style": {
        "backgroundColor": "white",
        "color": "black"
    }
}

if modo == "PONTOS":
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_mapa,
        get_position='[COD_LONGITUDE, COD_LATITUDE]',
        get_fill_color="cor",
        get_radius=20,
        radius_min_pixels=2,
        radius_max_pixels=8,
        pickable=True,
        opacity=0.7
    )
else:
    layer = pdk.Layer(
        "HexagonLayer",
        data=df_mapa,
        get_position='[COD_LONGITUDE, COD_LATITUDE]',
        radius=250,
        elevation_scale=20,
        extruded=True,
        pickable=True,
        auto_highlight=True
    )

deck = pdk.Deck(
    layers=[layer],
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style="light"
)

st.pydeck_chart(deck, use_container_width=True)

st.subheader("Dados filtrados")
st.dataframe(
    df_filtrado[
        ["NUM_LIGACAO", "CIDADE", "NOM_BAIRRO_CIDADE", "TIPO_FATURAMENTO", "GC"]
    ],
    use_container_width=True,
    height=400
)

st.markdown("""
### Legenda
- Vermelho: Água  
- Verde: Água + Esgoto  
- Marrom: T.E.E  
- Laranja: Água + T.E.E  
- Azul: Água + Esgoto + T.E.E  
- Dourado: GC  
""")