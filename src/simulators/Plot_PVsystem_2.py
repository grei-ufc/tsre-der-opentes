import pandas as pd
import os
import pathlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker

#CARREGAMENTO DOS DADOS

script_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df = pd.read_csv(pathlib.Path(script_path).joinpath("output", "resultados.csv"))
df[' Hora'] = pd.to_datetime(df[' Hora'])
df_2 = pd.read_csv(pathlib.Path(script_path).joinpath("output", "result_Caio.csv"))
'''
minutos = int((df.loc[1, ' Hora'].minute) - (df.loc[0, ' Hora'].minute))
horas = minutos/60
qtd_pontos = df.index.size
dias = int((horas*qtd_pontos)/24)
'''

#CÁLCULOS DOS COMPARATIVOS

#Potência:
df['Dif_P'] = abs((df_2['PV-0.PV_0-P_gen'] - df['PanelkW']))
dif_total=0
maior_dif=0
j=0
for i, valor in enumerate(df['Dif_P']):
    dif_total=dif_total+df.at[i, 'Dif_P']
    j=j+1
    if abs(df.at[i, 'Dif_P']) > abs(maior_dif):
        maior_dif = df.at[i, 'Dif_P']
maior_dif_P = maior_dif
dif_media_P = dif_total/j
print('\nDiferença média da potência gerada do simulador em relação ao OpenDSS:', f"{dif_media_P:.3f}", 'kW')
print('A maior diferença da potência gerada é:', f"{maior_dif_P:.3f}",'kW')

#V1:
df['Dif_V1'] = abs((df_2['DSS-0.Bus-671-V1_pu']-df[' V1']))*2.4
df['Dif_V1_pu'] = abs((df_2['DSS-0.Bus-671-V1_pu']-df[' V1']))
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
df['Dif_V2'] = abs((df_2['DSS-0.Bus-671-V2_pu']-df[' V2']))*2.4
df['Dif_V2_pu'] = abs((df_2['DSS-0.Bus-671-V2_pu']-df[' V2']))
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
df['Dif_V3'] = abs((df_2['DSS-0.Bus-671-V3_pu']-df[' V3']))*2.4
df['Dif_V3_pu'] = abs((df_2['DSS-0.Bus-671-V3_pu']-df[' V3']))
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

#PLOTS

#Apenas grandezas:

x = df[' Hora']

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


#GRANDEZAS E DIFERENÇAS

fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 2, figsize=(13, 6), sharex=True)

ax1 = plt.subplot(4, 2, 1)
plt.plot(x, df['PanelkW'], label='OpenDSS')
plt.plot(x, df_2['PV-0.PV_0-P_gen'], linestyle='dashed', label='Simulador')
ax1.set_ylabel('Potência (kW)'), ax1.grid(True)
ax1.yaxis.set_major_locator(ticker.MultipleLocator(100))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax2 = plt.subplot(4, 2, 3)
plt.plot(x, df[' V1'], label='OpenDSS')
plt.plot(x, df_2['DSS-0.Bus-671-V1_pu'], linestyle='dashed', label='Simulador')
ax2.set_ylabel('V1 (pu)'),ax2.grid(True)
ax2.yaxis.set_major_locator(ticker.MultipleLocator(0.02))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax3 = plt.subplot(4, 2, 5)
plt.plot(x, df[' V2'], label='OpenDSS')
plt.plot(x, df_2['DSS-0.Bus-671-V2_pu'], linestyle='dashed', label='Simulador')
ax3.set_ylabel('V2 (pu)'),ax3.grid(True)
ax3.yaxis.set_major_locator(ticker.MultipleLocator(0.005))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax4 = plt.subplot(4, 2, 7)
plt.plot(x, df[' V3'], label='OpenDSS')
plt.plot(x, df_2['DSS-0.Bus-671-V3_pu'], linestyle='dashed', label='Simulador')
ax4.set_ylabel('V3 (pu)'),ax4.grid(True)
ax4.yaxis.set_major_locator(ticker.MultipleLocator(0.02))
plt.legend(loc='upper right', fontsize=8, frameon=True)

ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax4.xaxis.set_major_locator(mdates.HourLocator(interval=6))
ax4.tick_params(axis='x', rotation=45)
ax4.set_xlim(pd.to_datetime('2016-01-01 00:00:00'), pd.to_datetime('2016-01-05 00:00:00'))

ax5 = plt.subplot(4, 2, 2)
plt.plot(x, df['Dif_P'])
ax5.set_ylabel('Delta P (kW)'), ax5.grid(True)
ax5.yaxis.set_major_locator(ticker.MultipleLocator(10))

ax6 = plt.subplot(4, 2, 4)
plt.plot(x, df['Dif_V1_pu'])
ax6.set_ylabel('Delta V1 (pu)'), ax6.grid(True)

ax7 = plt.subplot(4, 2, 6)
plt.plot(x, df['Dif_V2_pu'])
ax7.set_ylabel('Delta V2 (pu)'), ax7.grid(True)

ax8 = plt.subplot(4, 2, 8)
plt.plot(x, df['Dif_V3_pu'])
ax8.set_ylabel('Delta V3 (pu)'), ax8.grid(True)

ax8.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax8.xaxis.set_major_locator(mdates.HourLocator(interval=6))
ax8.tick_params(axis='x', rotation=45)
ax8.set_xlim(pd.to_datetime('2016-01-01 00:00:00'), pd.to_datetime('2016-01-05 00:00:00'))

fig.text(0.3, 0.9, 'Potência e Tensões', ha='center', va='center', fontsize=12)
fig.text(0.72, 0.9, 'Diferenças (Erros)', ha='center', va='center', fontsize=12)

plt.suptitle('Comparativo de potência injetada e tensão na barra 671', weight='bold')

plt.show()