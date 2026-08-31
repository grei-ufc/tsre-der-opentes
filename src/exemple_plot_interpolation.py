import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.interpolate import PchipInterpolator
import os

# Dados simulados de temperatura (medidos a cada hora durante um período de 12 horas)
# Simulando grandes e rápidas variações
time_1h = pd.date_range("06:00", "18:00", freq="1h")
# Valores com muitas flutuações (por exemplo, passagens de nuvens espessas, vento frio, etc)
temperature_1h = [15, 23, 22, 23, 25, 30, 27, 28, 20, 25, 24, 23, 16]

df_1h = pd.DataFrame({'temperature': temperature_1h}, index=time_1h)

# Criando a linha do tempo de 1 minuto para interpolar
time_1min = pd.date_range("06:00", "18:00", freq="1min")

# 1. Interpolação Linear (Pandas padrão)
df_linear = df_1h.reindex(time_1min).interpolate(method='time')

# 2. Interpolação PCHIP (Preserva a monotonicidade, curva suave)
# Converte o tempo em segundos para a matemática do Scipy
x_1h = (df_1h.index - df_1h.index[0]).total_seconds()
x_1min = (time_1min - df_1h.index[0]).total_seconds()

pchip = PchipInterpolator(x_1h, df_1h['temperature'])
temp_pchip = pchip(x_1min)

# Plotando
plt.figure(figsize=(11, 6))

# Plot da interpolação PCHIP (Z-order 2 para ficar em baixo)
plt.plot(time_1min, temp_pchip, label='PCHIP (Curva suave, acompanha inércia térmica)', 
         linewidth=2.5, color='green', zorder=2)

# Plot da interpolação Linear (Z-order 3 para ficar por cima)
plt.plot(time_1min, df_linear['temperature'], label='Linear (Sobe e desce em zig-zag)', 
         linestyle='--', color='red', alpha=0.9, linewidth=2, zorder=3)

# Pontos reais do dataset (coletados da estação de 1 em 1h)
# Z-order 4 para os pontos ficarem acima de todas as linhas
plt.plot(df_1h.index, df_1h['temperature'], 'o', markersize=8, 
         label='Dados Originais (1 em 1h)', color='blue', zorder=4)

# Customização do gráfico
plt.title('Comparação: Interpolação Linear vs PCHIP (Temperatura)', fontsize=14)
plt.xlabel('Hora do Dia', fontsize=12)
plt.ylabel('Temperatura (°C)', fontsize=12)
plt.grid(True, linestyle=':', alpha=0.7)
plt.legend(fontsize=11)

# Formatando o eixo X para exibir apenas as horas e minutos (ex: 08:00)
plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
plt.gcf().autofmt_xdate() # Rotaciona levemente se ficar apertado

plt.tight_layout()

# Definindo o caminho de salvamento para a pasta Downloads do seu Windows (WSL)
downloads_dir = "/mnt/c/Users/pvict/Downloads"

# Fallback de segurança
if not os.path.exists(downloads_dir):
    downloads_dir = os.path.expanduser("~/Downloads")
    os.makedirs(downloads_dir, exist_ok=True)

save_path = os.path.join(downloads_dir, "comparacao_interpolacao_temperatura.png")
plt.savefig(save_path, dpi=300)
print(f"Gráfico salvo com sucesso em: {save_path}")

