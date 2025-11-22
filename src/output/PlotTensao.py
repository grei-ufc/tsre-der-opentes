import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
# Carregar os dados dos arquivos CSV
data = pd.read_csv('results.csv')
data1 = pd.read_csv('results.csv')

# --- MODIFICAÇÃO PRINCIPAL: Ajuste da frequência para 30 segundos ---
try:
    # Alteramos o parâmetro 'freq' de 'T' (minuto) para '30S' (30 segundos).
    # O resto do código se adapta automaticamente a esta nova frequência.
    time_index = pd.date_range(start='07:00:00', periods=len(data), freq='60S')

    # Defina este índice para ambos os DataFrames.
    data.index = time_index
    data1.index = time_index
except ValueError as e:
    print(f"Erro: O número de linhas nos dados ({len(data)}) não corresponde ao índice de tempo gerado.")
    print("Verifique se a frequência ('freq') e a duração da simulação estão corretas.")
    exit()

# Selecionar as colunas
# col1 = 'Grid-0.0-LV2.101 Bus 102-p_mw'
# col2 = 'Grid-0.0-LV2.101 Bus 42-vm_pu'

# # Ao selecionar as colunas, elas agora são Series com um DatetimeIndex
# pv_data1 = data[col1]
# pv_data1_alt = data1[col1]

# pv_data2 = data[col2]
# pv_data2_alt = data1[col2]

#######################################################
 # Certifique-se de que numpy está importado

# --- SEU CÓDIGO EXISTENTE ---
# (Assumindo que 'data' e 'data1' já foram carregados do CSV)
col1 = 'Grid-0.0-LV6.201 Bus 21-vm_pu' #Barra 21
col2 = 'Grid-0.0-LV6.201 Bus 17-vm_pu' #Barra 17

# Ao selecionar as colunas, elas agora são Series com um DatetimeIndex
pv_data1 = data[col1]       # Tensão na Barra 2, COM controle
pv_data1_alt = data1[col1]  # Tensão na Barra 2, SEM controle

pv_data2 = data[col2]       # Tensão na Barra 42, COM controle
pv_data2_alt = data1[col2]  # Tensão na Barra 42, SEM controle

# --- CÓDIGO ADICIONAL PARA CÁLCULO DE CUSTO ---

# 1. Defina o limite de tensão a ser penalizado
v_limite = 1.05

# 2. Crie uma função para calcular o custo de sobretensão
def calcular_custo_sobretensao(tensoes, v_lim):
    """
    Calcula o custo de sobretensão (soma dos desvios quadráticos acima de um limite).
    
    Args:
        tensoes (pd.Series): Uma série de medições de tensão.
        v_lim (float): O limite de tensão a partir do qual a penalidade é aplicada.
        
    Returns:
        float: O custo total de sobretensão.
    """
    # Calcula os desvios em relação ao limite
    desvios = tensoes - v_lim
    
    # Zera os desvios não-positivos (tensões aceitáveis)
    desvios_penalizaveis = desvios.clip(lower=0)
    
    # Retorna a soma dos quadrados dos desvios penalizáveis
    custo = (desvios_penalizaveis).sum()
    return custo

# 3. Aplique a função para cada conjunto de dados
custo_bus2_com_controle = calcular_custo_sobretensao(pv_data1, v_limite)
custo_bus2_sem_controle = calcular_custo_sobretensao(pv_data1_alt, v_limite)

custo_bus42_com_controle = calcular_custo_sobretensao(pv_data2, v_limite)
custo_bus42_sem_controle = calcular_custo_sobretensao(pv_data2_alt, v_limite)


# 4. Imprima um relatório comparativo
print("--- Análise de Custo de Sobretensão (Limite > 1.05 pu) ---\n")

# Análise para a Barra 2
print(f"Barra Analisada: '{col1}'")
print(f"Custo (Sem Controle): {custo_bus2_sem_controle:.6f}")
print(f"Custo (Com Controle): {custo_bus2_com_controle:.6f}")

# Calcula a melhoria percentual
if custo_bus2_sem_controle > 0:
    reducao_percentual1 = (1 - (custo_bus2_com_controle / custo_bus2_sem_controle)) * 100
    print(f"Resultado: O controle reduziu o custo de sobretensão em {reducao_percentual1:.2f}%\n")
else:
    print("Resultado: Não houve sobretensão no cenário base para esta barra.\n")

# Análise para a Barra 42
print("---------------------------------------------------------")
print(f"Barra Analisada: '{col2}'")
print(f"Custo (Sem Controle): {custo_bus42_sem_controle:.6f}")
print(f"Custo (Com Controle): {custo_bus42_com_controle:.6f}")

# Calcula a melhoria percentual
if custo_bus42_sem_controle > 0:
    reducao_percentual2 = (1 - (custo_bus42_com_controle / custo_bus42_sem_controle)) * 100
    print(f"Resultado: O controle reduziu o custo de sobretensão em {reducao_percentual2:.2f}%")
else:
    print("Resultado: Não houve sobretensão no cenário base para esta barra.")
############################

# --- Plotagem (sem alterações aqui) ---
# Criar subplots
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
lab1 = 'Controle Volt-Var'

# --- Primeiro gráfico ---
ax1.plot(pv_data1, label=f'{lab1}', linewidth=2.5)
ax1.plot(pv_data1_alt, label='Sem Controle', linestyle='--', linewidth=2.5)
ax1.axhline(y=1.05, color='red', linestyle='--', linewidth=2, label='Limite 1.05')
ax1.set_title('Tensão em pu na Barra 3')
ax1.set_ylabel('Tensão (pu)')
ax1.grid(True)
ax1.legend()
import numpy as np
yticks = np.arange(1.0, 1.1, 0.01)  # de 1.0 a 1.1 com passo de 0.01

ax1.set_ylim(1.0, 1.1)
ax2.set_ylim(1.0, 1.1)

ax1.set_yticks(yticks)
ax2.set_yticks(yticks)
# --- Segundo gráfico ---
ax2.plot(pv_data2, label=f'{lab1}', linewidth=2.5)
ax2.plot(pv_data2_alt, label='Sem Controle', linestyle='--', linewidth=2.5)
ax2.axhline(y=1.05, color='red', linestyle='--', linewidth=2, label='Limite 1.05')
ax2.set_title('Tensão em pu na Barra 26')
ax2.set_ylabel('Tensão (pu)')
ax2.grid(True)
ax2.legend()

# --- Formatação do eixo X (sem alterações aqui) ---
for ax in [ax1, ax2]:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.set_xlabel('Horário da Simulação (HH:MM)')

# Ajustar layout para evitar sobreposição
plt.tight_layout()

# Mostrar o gráfico
plt.show()