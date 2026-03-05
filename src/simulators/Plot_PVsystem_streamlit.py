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

st.set_page_config(page_title="Comparação OpenDSS x Simulador (Caio Lucas)", page_icon="⚡", layout="centered")

st.markdown("""
## 📊 Dashboard de Validação

Este aplicativo compara os resultados do **OpenDSS** (referência) com o **simulador próprio** desenvolvido em Python, permitindo avaliar a precisão do modelo.

### 🔧 Como usar
- **Seleção de fontes**: Escolha entre OpenDSS (linhas azuis contínuas), Simulador (linhas laranja) e/ou Diferença (erro) – exibida em roxo.
- **Seleção de grandezas**: Visualize Potência, Tensões e Correntes (apenas OpenDSS).

### 📈 Organização dos gráficos
Cada grandeza ocupa uma linha. Quando a diferença está ativa, há duas colunas:
- **Esquerda**: comparação OpenDSS vs Simulador.
- **Direita**: erro (diferença) com cores por fase.

O eixo x cobre o período de 01/01/2016 a 05/01/2016, com intervalo de 6 horas.

### 📊 Estatísticas (opcional)
Na barra lateral, ative a exibição das diferenças médias e máximas para avaliar a acurácia do simulador.
""")

# Opções disponíveis
opcoes_fonte = ["OpenDSS", "Simulador", "Diferença (erro)"]
opcoes_grandeza = ["Potência", "Tensões", "Correntes"] 

# Seleção de fontes (múltipla)
fontes = st.multiselect(
    "Selecione as fontes de dados para exibir:",
    opcoes_fonte,
    default=["OpenDSS", "Simulador"]  # valor inicial
)
# Seleção de grandezas (múltipla)
grandezas = st.multiselect(
    "Selecione as grandezas para serem exibidas:",
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
    # Apenas diferenças: uma coluna com os gráficos de erro
    modo = "diferenca"
    ncols = 1
elif (tem_open or tem_sim) and not tem_dif:
    # Apenas comparação: uma coluna com OpenDSS e/ou Simulador
    modo = "comparacao"
    ncols = 1
elif (tem_open or tem_sim) and tem_dif:
    # Ambos: duas colunas (comparação à esquerda, diferença à direita)
    modo = "ambos"
    ncols = 2
else:
    # Nenhuma fonte selecionada (já deve ter sido tratado antes)
    st.warning("Selecione pelo menos uma fonte.")
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
fig = plt.figure(figsize=(12*ncols, 2 * n_series), dpi=480)
gs = GridSpec(n_series, ncols, figure=fig, hspace=0.5, wspace=0.15)

x = df[' Hora']
tem_diferenca_global = "Diferença (erro)" in fontes

# Listas para guardar os eixos (útil para formatação posterior)
axes_esq = []
axes_dir = []

for i, serie in enumerate(series):
    if modo == "comparacao":
        # Apenas um eixo com a comparação OpenDSS/Simulador
        ax = fig.add_subplot(gs[i, 0])
        axes_esq.append(ax)
        ax.grid(True)
        ax.set_ylabel(serie["ylabel"])

        if tem_open:
            ax.plot(x, df[serie["col_open"]], label='OpenDSS', color='blue', linestyle='-', linewidth=1)
        if tem_sim and serie["tem_sim"]:
            ax.plot(x, df_2[serie["col_sim"]], label='Simulador', color='red', linestyle='-', linewidth=1)

        if (tem_open) or (tem_sim and serie["tem_sim"]):
            ax.legend(loc='upper right', fontsize=8, frameon=True)

        if serie.get("major_locator_esq"):
            ax.yaxis.set_major_locator(serie["major_locator_esq"])

    elif modo == "diferenca":
        # Apenas um eixo com a diferença
        ax = fig.add_subplot(gs[i, 0])
        axes_esq.append(ax)
        ax.grid(True)
        ax.set_ylabel(serie["ylabel_dif"])

        if serie["tem_dif"]:
            ax.plot(x, df[serie["col_dif"]], color='purple', linestyle='-', linewidth=1)
            if serie.get("major_locator_dir"):
                ax.yaxis.set_major_locator(serie["major_locator_dir"])
        else:
            # Se a série não tem diferença, oculta o eixo
            ax.set_visible(False)

    else:  # modo == "ambos"
        # Eixo esquerdo: comparação
        ax_esq = fig.add_subplot(gs[i, 0])
        axes_esq.append(ax_esq)
        ax_esq.grid(True)
        ax_esq.set_ylabel(serie["ylabel"])

        if tem_open:
            ax_esq.plot(x, df[serie["col_open"]], label='OpenDSS', color='blue', linestyle='-', linewidth=1)
        if tem_sim and serie["tem_sim"]:
            ax_esq.plot(x, df_2[serie["col_sim"]], label='Simulador', color='red', linestyle='-', linewidth=1)

        if (tem_open) or (tem_sim and serie["tem_sim"]):
            ax_esq.legend(loc='upper right', fontsize=8, frameon=True)

        if serie.get("major_locator_esq"):
            ax_esq.yaxis.set_major_locator(serie["major_locator_esq"])

        # Eixo direito: diferença
        ax_dir = fig.add_subplot(gs[i, 1])
        axes_dir.append(ax_dir)
        ax_dir.grid(True)

        if serie["tem_dif"]:
            ax_dir.set_ylabel(serie["ylabel_dif"])
            ax_dir.plot(x, df[serie["col_dif"]], color='purple'
            '', linestyle='-', linewidth=1)
            if serie.get("major_locator_dir"):
                ax_dir.yaxis.set_major_locator(serie["major_locator_dir"])
        else:
            ax_dir.set_visible(False)

# -------------------------------------------------------------------
# Configurar o eixo x para todos os subplots visíveis
if modo in ["comparacao", "diferenca"]:
    # Apenas uma coluna: formatar os eixos em axes_esq
    for ax in axes_esq:
        if ax.get_visible():
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
            ax.tick_params(axis='x', rotation=45)
            ax.set_xlim(pd.to_datetime('2016-01-01 00:00:00'), 
                        pd.to_datetime('2016-01-05 00:00:00'))
    # Rótulo x no último subplot
    if axes_esq and axes_esq[-1].get_visible():
        axes_esq[-1].set_xlabel('Hora')

else:  # modo == "ambos"
    # Formatar eixos esquerdos
    for ax in axes_esq:
        if ax.get_visible():
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
            ax.tick_params(axis='x', rotation=45)
            ax.set_xlim(pd.to_datetime('2016-01-01 00:00:00'), 
                        pd.to_datetime('2016-01-05 00:00:00'))
    # Formatar eixos direitos
    for ax in axes_dir:
        if ax.get_visible():
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
            ax.tick_params(axis='x', rotation=45)
            ax.set_xlim(pd.to_datetime('2016-01-01 00:00:00'), 
                        pd.to_datetime('2016-01-05 00:00:00'))
    # Rótulos x nos últimos subplots
    axes_esq[-1].set_xlabel('Hora')
    if axes_dir and axes_dir[-1].get_visible():
        axes_dir[-1].set_xlabel('Hora')

    # Títulos das colunas (apenas no modo ambos)
    fig.text(0.3, 0.92, 'Potência e Tensões', ha='center', va='center', fontsize=12)
    fig.text(0.72, 0.92, 'Diferenças (Erros)', ha='center', va='center', fontsize=12)

plt.suptitle('Comparativo de grandezas na barra 671', weight='bold', y=1)
plt.tight_layout()

# Exibir no Streamlit
st.pyplot(fig)