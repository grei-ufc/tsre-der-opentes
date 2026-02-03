import pandas as pd
import numpy as np

# Parâmetros configuráveis
PRIMEIROS_VALORES = 2880  # Quantidade de primeiros valores a considerar
INTERVALO = 10            # Tamanho da janela para cálculo da média

# Read the CSV file
irrad = pd.read_csv("src/data/solar_data_Bremen_minutes.csv")

# Pegar os valores da segunda coluna
valores = (irrad[irrad.columns[1]].values)/1000

# Processar apenas os primeiros valores
primeiros_valores = valores[:PRIMEIROS_VALORES]
valores_selecionados = []

# Calcular a média a cada INTERVALO dos primeiros valores
for i in range(0, len(primeiros_valores), INTERVALO):
    # Pegar o bloco de valores do intervalo
    bloco = primeiros_valores[i:i+INTERVALO]
    
    # Substituir NaN por 0 no bloco
    bloco_sem_nan = np.where(pd.isna(bloco), 0, bloco)
    
    # Calcular a média do bloco
    media_bloco = np.mean(bloco_sem_nan)
    
    # Adicionar a média formatada
    valores_selecionados.append(f"{media_bloco:.10f}")

# Quantidade total de itens após o processamento
npts = len(valores_selecionados)

# Criar a string no formato DSS
conteudo_dss = f"New LoadShape.MyShapePV1 npts={npts} minterval=10 mult=({', '.join(valores_selecionados)})\n"

# Salvar como arquivo .dss
nome_arquivo = "src/data/13Bus/LoadShapePV.dss"
with open(nome_arquivo, "w") as f:
    f.write(conteudo_dss)

print(f"Processamento concluído!")
print(f"Calculadas {npts} médias dos primeiros {PRIMEIROS_VALORES} valores (janela de {INTERVALO} valores cada)")
print(f"Cada média representa {INTERVALO} valores originais")