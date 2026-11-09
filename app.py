
import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(
    page_title="Curtailment Brasil",
    page_icon="⚡",
    layout="wide"
)

st.title("Análise de Curtailment")
st.caption("Plataforma pública de análise de geração renovável")
st.divider()


dados = pd.DataFrame({
    "Mes": ["Jul", "Ago", "Set", "Out"],
    "Curtailment_GWh": [120, 145, 180, 210]
})

fig = px.bar(
    dados,
    x="Mes",
    y="Curtailment_GWh",
    title="Evolução mensal do curtailment"
)

st.plotly_chart(fig, use_container_width=True)
