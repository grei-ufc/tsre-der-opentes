import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
from matplotlib.gridspec import GridSpec
import os
import pathlib

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

# PLOTS

st.set_page_config(page_title="Comparação entre o simulador desenvolvido e o simulador nativo do OpenDSS", page_icon="⚡", layout="wide")

st.title("⚡ Comparação entre o simulador desenvolvido e o simulador nativo do OpenDSS")

# Opções disponíveis
opcoes_fonte = ["OpenDSS", "Simulador", "Diferença (erro)"]
opcoes_grandeza = ["Potência", "Tensões", "Correntes"] 

# Seleção de fontes (múltipla)
fontes = st.multiselect(
    "Selecione as fontes a exibir:",
    opcoes_fonte,
    default=["OpenDSS", "Simulador"]  # valor inicial
)
# Seleção de grandezas (múltipla)
grandezas = st.multiselect(
    "Selecione as grandezas:",
    opcoes_grandeza,
    default=["Potência", "Tensões"]
)

if "OpenDSS" in fontes or "Simulador" in fontes:
    if "Diferença (erro)" in fontes:
        n_colunas = 2
    else:
        n_colunas = 1
elif "Diferença (erro)" in fontes:
    n_colunas = 1
else:
    st.warning("Selecione pelo menos uma fonte de dados.")
    st.stop()

# -------------------------------------------------------------------
# Definição dos grupos e suas séries
# Cada série contém: nome, colunas, rótulos, cor, flags e locators de ticks
grupos = {}

# Potência
grupos["Potência"] = [
    {
        "nome": "Potência",
        "col_open": "PanelkW",
        "col_sim": "PV-0.PV_0-P_gen",
        "col_dif": "Dif_P",
        "ylabel": "Potência (kW)",
        "ylabel_dif": "ΔP (kW)",
        "cor": "blue",
        "tem_sim": True,
        "tem_dif": True,
        "major_locator_esq": ticker.MultipleLocator(100),
        "major_locator_dir": ticker.MultipleLocator(10)
    }
]

# Tensões
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
        "major_locator_esq": ticker.MultipleLocator(0.02),
        "major_locator_dir": None
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
        "major_locator_esq": ticker.MultipleLocator(0.005),
        "major_locator_dir": None
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
        "major_locator_esq": ticker.MultipleLocator(0.02),
        "major_locator_dir": None
    }
]

# Correntes (ajuste os nomes das colunas conforme seu DataFrame)
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
        "major_locator_esq": None,
        "major_locator_dir": None
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
        "major_locator_esq": None,
        "major_locator_dir": None
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
        "major_locator_esq": None,
        "major_locator_dir": None
    }
]

# -------------------------------------------------------------------
# Construir a lista plana de séries a partir dos grupos selecionados
series = []
for grupo in grandezas:
    if grupo in grupos:
        series.extend(grupos[grupo])

n_series = len(series)
if n_series == 0:
    st.warning("Selecione pelo menos uma grandeza.")
    st.stop()

# -------------------------------------------------------------------
# Criar a figura com GridSpec
fig = plt.figure(figsize=(13, 2 * n_series))
gs = GridSpec(n_series, n_colunas, figure=fig, hspace=0.3, wspace=0.15)

x = df[' Hora']
tem_diferenca_global = "Diferença (erro)" in fontes

# Listas para guardar os eixos (útil para formatação posterior)
axes_esq = []
axes_dir = []

# Loop sobre cada série
for i, serie in enumerate(series):
    # --- Eixo esquerdo (comparação OpenDSS vs Simulador) ---
    ax_esq = fig.add_subplot(gs[i, 0])
    axes_esq.append(ax_esq)
    ax_esq.grid(True)
    ax_esq.set_ylabel(serie["ylabel"])

    # Plotar OpenDSS
    if "OpenDSS" in fontes:
        ax_esq.plot(x, df[serie["col_open"]], 
                   label='OpenDSS', color=serie["cor"], linestyle='-')

    # Plotar Simulador (se disponível para esta série)
    if "Simulador" in fontes and serie["tem_sim"]:
        ax_esq.plot(x, df_2[serie["col_sim"]], 
                   label='Simulador', color=serie["cor"], linestyle='--')

    # Legenda (se houver pelo menos uma fonte plotada)
    if ("OpenDSS" in fontes) or ("Simulador" in fontes and serie["tem_sim"]):
        ax_esq.legend(loc='upper right', fontsize=8, frameon=True)

    # Aplicar locator personalizado se existir
    if serie.get("major_locator_esq"):
        ax_esq.yaxis.set_major_locator(serie["major_locator_esq"])

    # --- Eixo direito (diferença) ---
    ax_dir = fig.add_subplot(gs[i, 1])
    axes_dir.append(ax_dir)
    ax_dir.grid(True)

    if tem_diferenca_global and serie["tem_dif"]:
        ax_dir.set_ylabel(serie["ylabel_dif"])
        ax_dir.plot(x, df[serie["col_dif"]], 
                   color=serie["cor"], linestyle='-', linewidth=1.5)
        if serie.get("major_locator_dir"):
            ax_dir.yaxis.set_major_locator(serie["major_locator_dir"])
    else:
        # Oculta o eixo se não houver diferença para esta série
        ax_dir.set_visible(False)

# -------------------------------------------------------------------
# Configurar o eixo x para todos os subplots visíveis
for ax in axes_esq + axes_dir:
    if ax.get_visible():
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        ax.tick_params(axis='x', rotation=45)
        ax.set_xlim(pd.to_datetime('2016-01-01 00:00:00'), 
                    pd.to_datetime('2016-01-05 00:00:00'))

# Colocar o rótulo do eixo x apenas nos últimos subplots de cada coluna
for ax in [axes_esq[-1], axes_dir[-1]]:
    if ax.get_visible():
        ax.set_xlabel('Hora')

# Títulos das colunas
fig.text(0.3, 0.98, 'Potência e Tensões', ha='center', va='center', fontsize=12)
fig.text(0.72, 0.98, 'Diferenças (Erros)', ha='center', va='center', fontsize=12)

plt.suptitle('Comparativo de grandezas na barra 671', weight='bold', y=1.02)
plt.tight_layout()

# -------------------------------------------------------------------
# Exibir no Streamlit
st.pyplot(fig)








#Apenas grandezas:

'''

fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(13, 6), sharex=True)

ax1 = plt.subplot(4, 1, 1)
plt.plot(x, df['PanelkW'], label='OpenDSS')
plt.plot(x, df_2['PV-0.PV_0-P_gen'], linestyle='dashed', label='Simulador')
ax1.set_ylabel('Potência (kW)'), ax1.grid(True)
ax1.yaxis.set_major_locator(ticker.MultipleLocator(100))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax2 = plt.subplot(4, 1, 2)
plt.plot(x, df[' V1'], label='OpenDSS')
plt.plot(x, df_2['DSS-0.Bus-671-V1_pu'], linestyle='dashed', label='Simulador')
ax2.set_ylabel('V1 (pu)'),ax2.grid(True)
ax2.yaxis.set_major_locator(ticker.MultipleLocator(0.02))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax3 = plt.subplot(4, 1, 3)
plt.plot(x, df[' V2'], label='OpenDSS')
plt.plot(x, df_2['DSS-0.Bus-671-V2_pu'], linestyle='dashed', label='Simulador')
ax3.set_ylabel('V2 (pu)'),ax3.grid(True)
ax3.yaxis.set_major_locator(ticker.MultipleLocator(0.005))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax4 = plt.subplot(4, 1, 4)
plt.plot(x, df[' V3'], label='OpenDSS')
plt.plot(x, df_2['DSS-0.Bus-671-V3_pu'], linestyle='dashed', label='Simulador')
ax4.set_ylabel('V3 (pu)'),ax4.grid(True)
ax4.yaxis.set_major_locator(ticker.MultipleLocator(0.02))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax4.xaxis.set_major_locator(mdates.HourLocator(interval=4))
ax4.tick_params(axis='x', rotation=45)
ax4.set_xlim(pd.to_datetime('2016-01-01 00:00:00'), pd.to_datetime('2016-01-05 00:00:00'))

plt.suptitle('Potência injetada e tensão na barra 671')

st.pyplot(fig)
'''