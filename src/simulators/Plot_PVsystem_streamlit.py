import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import pathlib
import numpy as np  # (já pode ser necessário para os cálculos)

script_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df = pd.read_csv(pathlib.Path(script_path).joinpath("output", "resultados.csv"))
df[' Hora'] = pd.to_datetime(df[' Hora'])
df_2 = pd.read_csv(pathlib.Path(script_path).joinpath("output", "result_Caio.csv"))

#CÁLCULOS DOS COMPARATIVOS

#Potência:
df['Dif_P'] = (df['PanelkW'] - df_2['PV-0.PV_0-P_gen'])
dif_total=0
maior_dif=0
j=0
for i, valor in enumerate(df['Dif_P']):
    dif_total=dif_total+abs(df.at[i, 'Dif_P'])
    j=j+1
    if abs(df.at[i, 'Dif_P']) > abs(maior_dif):
        maior_dif = df.at[i, 'Dif_P']
maior_dif_P = maior_dif
dif_media_P = dif_total/j
print('\nDiferença média da potência gerada do simulador em relação ao OpenDSS:', f"{dif_media_P:.3f}", 'kW')
print('A maior diferença da potência gerada é:', f"{maior_dif_P:.3f}",'kW')

#V1:
df['Dif_V1_pu'] = (df[' V1']-df_2['DSS-0.Bus-671-V1_pu'])
df['Dif_V1'] = (df['Dif_V1_pu'])*2.4
dif_total=0
maior_dif=0
j=0
for i, valor in enumerate(df['Dif_V1']):
    if df.at[i, 'Dif_V1'] < 0.07:
        dif_total=dif_total+df.at[i, 'Dif_V1']
        j=j+1
        if abs(df.at[i, 'Dif_V1']) > abs(maior_dif):
            maior_dif = df.at[i, 'Dif_V1']
maior_dif_V1 = maior_dif
maior_dif_V1_pu = maior_dif_V1/2.400
dif_media_V1 = dif_total/j
dif_media_V1_pu = dif_media_V1/2.400
print('\nDiferença média da tensão V1 do simulador em relação ao OpenDSS:', f"{dif_media_V1:.3f}",'kV','=',f"{dif_media_V1_pu:.3f}",'pu')
print('A maior diferença de tensão para V1 é:',f"{maior_dif_V1:.3f}",'kV','=',f"{maior_dif_V1_pu:.3f}",'pu')

#V2:
df['Dif_V2_pu'] = (df[' V2']-df_2['DSS-0.Bus-671-V2_pu'])
df['Dif_V2'] = (df['Dif_V2_pu'])*2.4
dif_total=0
maior_dif=0
j=0
for i, valor in enumerate(df['Dif_V2']):
    if df.at[i, 'Dif_V2'] < 0.07:
        dif_total=dif_total+df.at[i, 'Dif_V2']
        j=j+1
        if abs(df.at[i, 'Dif_V2']) > abs(maior_dif):
            maior_dif = df.at[i, 'Dif_V2']
maior_dif_V2 = maior_dif
maior_dif_V2_pu = maior_dif_V2/2.400
dif_media_V2 = dif_total/j
dif_media_V2_pu = dif_media_V2/2.400
print('\nDiferença média da tensão V2 do simulador em relação ao OpenDSS:', f"{dif_media_V2:.3f}",'kV','=',f"{dif_media_V2_pu:.3f}",'pu')
print('A maior diferença de tensão para V2 é:',f"{maior_dif_V2:.3f}",'kV','=',f"{maior_dif_V2_pu:.3f}",'pu')

#V3:
df['Dif_V3_pu'] = (df[' V3']-df_2['DSS-0.Bus-671-V3_pu'])
df['Dif_V3'] = (df['Dif_V3_pu'])*2.4
dif_total=0
maior_dif=0
j=0
for i, valor in enumerate(df['Dif_V3']):
    if df.at[i, 'Dif_V3'] < 0.07:
        dif_total=dif_total+df.at[i, 'Dif_V3']
        j=j+1
        if abs(df.at[i, 'Dif_V3']) > abs(maior_dif):
            maior_dif = df.at[i, 'Dif_V3']
maior_dif_V3 = maior_dif
maior_dif_V3_pu = maior_dif_V3/2.4
dif_media_V3 = dif_total/j
dif_media_V3_pu = dif_media_V3/2.4
print('\nDiferença média da tensão V3 do simulador em relação ao OpenDSS:', f"{dif_media_V3:.3f}",'kV','=',f"{dif_media_V3_pu:.3f}",'pu')
print('A maior diferença de tensão para V3 é:',f"{maior_dif_V3:.3f}",'kV','=',f"{maior_dif_V3_pu:.3f}",'pu')
print('')

# =====================================================
# EXIBIÇÃO DAS ESTATÍSTICAS NO STREAMLIT
# =====================================================
dados_estatisticas = {
    "Grandeza": ["Potência (kW)", "V1 (kV)", "V1 (pu)", "V2 (kV)", "V2 (pu)", "V3 (kV)", "V3 (pu)"],
    "Diferença Média": [f"{dif_media_P:.3f}", f"{dif_media_V1:.3f}", f"{dif_media_V1_pu:.3f}",
                        f"{dif_media_V2:.3f}", f"{dif_media_V2_pu:.3f}", f"{dif_media_V3:.3f}", f"{dif_media_V3_pu:.3f}"],
    "Maior Diferença": [f"{maior_dif_P:.3f}", f"{maior_dif_V1:.3f}", f"{maior_dif_V1_pu:.3f}",
                        f"{maior_dif_V2:.3f}", f"{maior_dif_V2_pu:.3f}", f"{maior_dif_V3:.3f}", f"{maior_dif_V3_pu:.3f}"]
}
df_estatisticas = pd.DataFrame(dados_estatisticas)

with st.sidebar.expander("📊 Estatísticas de Erro", expanded=False):
    st.dataframe(df_estatisticas, use_container_width=True, hide_index=True)

# PLOTS

st.set_page_config(page_title="Comparação OpenDSS x Simulador (Caio Lucas)", page_icon="⚡", layout="wide")

st.markdown("""
## 📊 Dashboard de Validação

Este aplicativo compara os resultados do **OpenDSS** (referência) com o **simulador próprio** desenvolvido em Python, permitindo avaliar a precisão do modelo.

### 🔧 Como usar
- **Seleção de fontes**: Escolha entre OpenDSS (linhas azuis contínuas), Simulador (linhas laranja) e/ou Diferença (erro) – exibida em roxo.
- **Seleção de grandezas**: Visualize Potência, Tensões e Correntes (apenas OpenDSS).

### 📈 Organização dos gráficos
Cada grandeza ocupa uma linha. Quando a diferença está ativa, há duas colunas:
- **Esquerda**: comparação OpenDSS vs Simulador.
- **Direita**: erro (diferença).

O eixo x cobre o período de quatro dias a partir de 01/01/2016, com intervalo de 6 horas.

""")

# Opções disponíveis
opcoes_fonte = ["OpenDSS", "Simulador", "Diferença (erro)"]
opcoes_grandeza = ["Potência", "Tensões", "Correntes"] 

with st.sidebar:
    st.header("Configurações de Visualização")
    
    fontes = st.multiselect(
        "Fontes de dados:",
        opcoes_fonte,
        default=["OpenDSS", "Simulador"]
    )
    
    grandezas = st.multiselect(
        "Grandezas:",
        opcoes_grandeza,
        default=["Potência", "Tensões"]
    )


# -------------------------------------------------------------------
# Verificar quais fontes estão selecionadas
tem_open = "OpenDSS" in fontes
tem_sim = "Simulador" in fontes
tem_dif = "Diferença (erro)" in fontes

# Definir o modo de exibição com base nas fontes ativas
if tem_dif and not (tem_open or tem_sim):
    modo = "diferenca"
    ncols = 1
elif (tem_open or tem_sim) and not tem_dif:
    modo = "comparacao"
    ncols = 1
elif (tem_open or tem_sim) and tem_dif:
    modo = "ambos"
    ncols = 2
else:
    st.warning("Selecione pelo menos uma fonte.")
    st.stop()

grupos = {}

grupos["Potência"] = [
    {
        "nome": "Potência",
        "col_open": "PanelkW",
        "col_sim": "PV-0.PV_0-P_gen",
        "col_dif": "Dif_P",
        "ylabel": "Potência (kW)",
        "ylabel_dif": "ΔP (kW)",
        "cor": "blue",  # (não será mais usado, mas pode manter)
        "tem_sim": True,
        "tem_dif": True,
        "ytick_dtick_esq": 100,
        "ytick_dtick_dir": 10
    }
]

grupos["Tensões"] = [
    {
        "nome": "V1",
        "col_open": " V1",
        "col_sim": "DSS-0.Bus-671-V1_pu",
        "col_dif": "Dif_V1_pu",
        "ylabel": "V1 (pu)",
        "ylabel_dif": "ΔV1 (pu)",
        "cor": "blue",
        "tem_sim": True,
        "tem_dif": True,
        "ytick_dtick_esq": 0.02,
        "ytick_dtick_dir": None
    },
    {
        "nome": "V2",
        "col_open": " V2",
        "col_sim": "DSS-0.Bus-671-V2_pu",
        "col_dif": "Dif_V2_pu",
        "ylabel": "V2 (pu)",
        "ylabel_dif": "ΔV2 (pu)",
        "cor": "green",
        "tem_sim": True,
        "tem_dif": True,
        "ytick_dtick_esq": 0.005,
        "ytick_dtick_dir": None
    },
    {
        "nome": "V3",
        "col_open": " V3",
        "col_sim": "DSS-0.Bus-671-V3_pu",
        "col_dif": "Dif_V3_pu",
        "ylabel": "V3 (pu)",
        "ylabel_dif": "ΔV3 (pu)",
        "cor": "red",
        "tem_sim": True,
        "tem_dif": True,
        "ytick_dtick_esq": 0.02,
        "ytick_dtick_dir": None
    }
]

grupos["Correntes"] = [
    {
        "nome": "I1",
        "col_open": " I1",
        "col_sim": None,
        "col_dif": None,
        "ylabel": "I1 (A)",
        "ylabel_dif": None,
        "cor": "purple",
        "tem_sim": False,
        "tem_dif": False,
        "ytick_dtick_esq": None,
        "ytick_dtick_dir": None
    },
    {
        "nome": "I2",
        "col_open": " I2",
        "col_sim": None,
        "col_dif": None,
        "ylabel": "I2 (A)",
        "ylabel_dif": None,
        "cor": "orange",
        "tem_sim": False,
        "tem_dif": False,
        "ytick_dtick_esq": None,
        "ytick_dtick_dir": None
    },
    {
        "nome": "I3",
        "col_open": " I3",
        "col_sim": None,
        "col_dif": None,
        "ylabel": "I3 (A)",
        "ylabel_dif": None,
        "cor": "brown",
        "tem_sim": False,
        "tem_dif": False,
        "ytick_dtick_esq": None,
        "ytick_dtick_dir": None
    }
]

series = []
for grupo in grandezas:
    if grupo in grupos:
        series.extend(grupos[grupo])

n_series = len(series)
if n_series == 0:
    st.warning("Selecione pelo menos uma grandeza.")
    st.stop()

# -------------------------------------------------------------------
# Criar figura Plotly com subplots
# -------------------------------------------------------------------
x_time = df[' Hora']  # variável usada em todos os plots

if modo == "comparacao":
    fig = make_subplots(
        rows=n_series, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=[serie["nome"] for serie in series]
    )
elif modo == "diferenca":
    fig = make_subplots(
        rows=n_series, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=[f"{serie['nome']} - Diferença" for serie in series]
    )
else:  # modo == "ambos"
    # Cria lista de títulos na ordem correta: (Comp1, Err1, Comp2, Err2, ...)
    titles = []
    for serie in series:
        titles.append(f"{serie['nome']}")
        titles.append(f"{serie['nome']} - Diferença")
    
    fig = make_subplots(
        rows=n_series, cols=2,
        shared_xaxes=True,
        vertical_spacing=0.05,
        horizontal_spacing=0.1,
        subplot_titles=titles
    )

for i, serie in enumerate(series):
    row = i + 1   # linhas no Plotly começam em 1

    # -------------------- Coluna 1 (esquerda) --------------------
    if modo in ["comparacao", "ambos"]:
        # OpenDSS
        if tem_open and serie["col_open"]:
            fig.add_trace(
                go.Scatter(
                    x=x_time, y=df[serie["col_open"]],
                    mode='lines',
                    name=f"OpenDSS - {serie['nome']}",
                    line=dict(color='blue', width=1),
                    legendgroup="opendss",
                    showlegend=(i == 0)  # só mostra na legenda geral uma vez
                ),
                row=row, col=1
            )
        # Simulador
        if tem_sim and serie["tem_sim"] and serie["col_sim"]:
            fig.add_trace(
                go.Scatter(
                    x=x_time, y=df_2[serie["col_sim"]],
                    mode='lines',
                    name=f"Simulador - {serie['nome']}",
                    line=dict(color='red', width=1),
                    legendgroup="simulador",
                    showlegend=(i == 0)
                ),
                row=row, col=1
            )

    # -------------------- Coluna 2 (direita) ou única coluna no modo diferença --------------------
    if modo in ["diferenca", "ambos"]:
        col = 2 if modo == "ambos" else 1
        if serie["tem_dif"] and serie["col_dif"]:
            fig.add_trace(
                go.Scatter(
                    x=x_time, y=df[serie["col_dif"]],
                    mode='lines',
                    name=f"Erro - {serie['nome']}",
                    line=dict(color='purple', width=1),
                    legendgroup="erro",
                    showlegend=(i == 0)
                ),
                row=row, col=col
            )

# -------------------------------------------------------------------
# Configurar eixos Y
# -------------------------------------------------------------------
for i, serie in enumerate(series):
    row = i + 1

    # Eixo Y da coluna 1 (comparação)
    if modo in ["comparacao", "ambos"]:
        fig.update_yaxes(
            title_text=serie["ylabel"],
            showgrid=True,
            gridcolor='lightgray',
            gridwidth=1,
            row=row, col=1,
            title_font_color='black',
            tickfont_color='black'
        )
        if serie.get("ytick_dtick_esq") is not None:
            fig.update_yaxes(dtick=serie["ytick_dtick_esq"], row=row, col=1)

    # Eixo Y da coluna 2 (erro) ou única coluna no modo diferença
    if modo in ["diferenca", "ambos"]:
        col = 2 if modo == "ambos" else 1
        if serie["tem_dif"] and serie["ylabel_dif"]:
            fig.update_yaxes(
                title_text=serie["ylabel_dif"],
                showgrid=True,
                gridcolor='lightgray',
                gridwidth=1,
                row=row, col=col,
                title_font_color='black',
                tickfont_color='black'
            )
            if serie.get("ytick_dtick_dir") is not None:
                fig.update_yaxes(dtick=serie["ytick_dtick_dir"], row=row, col=col)

# -------------------------------------------------------------------
# Configurar eixos X (compartilhados)
# -------------------------------------------------------------------
for row in range(1, n_series + 1):
    for col in range(1, ncols + 1):
        fig.update_xaxes(
            title_text="Hora" if row == n_series else "",
            tickformat="%H:%M",
            dtick=6 * 60 * 60 * 1000,
            range=[
                pd.to_datetime('2016-01-01 00:00:00'),
                pd.to_datetime('2016-01-05 00:00:00')
            ],
            showgrid=True,
            gridcolor='lightgray',
            gridwidth=1,
            title_font_color='black',   # título do eixo preto
            tickfont_color='black',      # valores dos ticks pretos
            row=row, col=col
        )

# -------------------------------------------------------------------
# Layout geral
# -------------------------------------------------------------------
fig.update_layout(
    title_text="Comparativo de grandezas na barra 671",
    margin=dict(t=120),
    title_x=0.4,  # <-- centraliza o título
    height=300 * n_series,  # <-- aumenta a altura para dar mais espaço
    template="plotly_white",
    hovermode="x unified",
    showlegend=True,
    plot_bgcolor='white',
    paper_bgcolor='white',
    font_color='black',
    title_font_color='black',
    legend_font_color='black',
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
)


st.plotly_chart(fig, use_container_width=True)