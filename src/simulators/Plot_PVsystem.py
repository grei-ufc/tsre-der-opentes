import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import matplotlib.ticker as ticker

# Carregar CSV do monitor
df = pd.read_csv("src/data/13Bus/IEEE13Nodeckt_Mon_v_barra680_1.csv")
df_2 = pd.read_csv("src/data/13Bus/IEEE13Nodeckt_Mon_pot_barra680_1.csv")*1000

# CONFIGURAÇÃO: Definir quantos minutos cada linha representa
minutos_por_linha = 10  # Altere este valor para o intervalo desejado (1, 5, 10, 15, etc.)

# Criar datetime inicial (meia-noite)
data_inicial = pd.to_datetime('2016-01-01 00:00:00')

# Criar Hora_completa: cada linha adiciona 'minutos_por_linha' minutos
df['Hora_completa'] = data_inicial + pd.to_timedelta(df.index * minutos_por_linha, unit='m')

print(df)

tensao_base_V = 2400  

# Converter para pu (dividir pela tensão base em Volts)
V1_pu = df[' V1'] / tensao_base_V
V2_pu = df[' V2'] / tensao_base_V
V3_pu = df[' V3'] / tensao_base_V

fig, (ax0, ax1, ax2, ax3) = plt.subplots(4, 1, figsize=(10, 6), sharex=True)

ax0.plot(df['Hora_completa'], df_2[' S1 (kVA)'], 'y-', label='Fase A')
ax0.set_ylabel('Potência (VA)'), ax0.legend(), ax0.grid(True, alpha=0.3)

ax1.plot(df['Hora_completa'], V1_pu, 'r-', label='Fase A')
ax1.set_ylabel('Tensão (pu)'), ax1.legend(), ax1.grid(True, alpha=0.3)

ax2.plot(df['Hora_completa'], V2_pu, 'g-', label='Fase B')
ax2.set_ylabel('Tensão (pu)'), ax2.legend(), ax2.grid(True, alpha=0.3)

ax3.plot(df['Hora_completa'], V3_pu, 'b-', label='Fase C')
ax3.set_ylabel('Tensão (pu)'), ax3.legend(), ax3.grid(True, alpha=0.3)

ax3.xaxis.set_major_formatter(DateFormatter('%H:%M'))
plt.suptitle('Tensões nas 3 Fases - Barra 680'), plt.tight_layout(), plt.show()
