import pandas as pd

# Parâmetros configuráveis
PRIMEIROS_VALORES = 2880  # Quantidade de primeiros valores a considerar
INTERVALO = 10            # Pegar um valor a cada X (10 em 10 neste caso)

# Read the CSV file
irrad = pd.read_csv("src/data/solar_data_Bremen_minutes.csv")

# Pegar os valores da segunda coluna
valores = (irrad[irrad.columns[1]].values)/1000

# Processar apenas os primeiros valores com amostragem
primeiros_valores = valores[:PRIMEIROS_VALORES]
valores_selecionados = []

# Pegar um a cada INTERVALO dos primeiros valores
for i in range(0, len(primeiros_valores), INTERVALO):
    v = primeiros_valores[i]
    if pd.isna(v):
        valores_selecionados.append('0.00000')
    else:
        valores_selecionados.append(f"{v:.5f}")

# Quantidade total de itens após o processamento
npts = len(valores_selecionados)

# Criar a string no formato DSS
conteudo_dss = f"New LoadShape.MyShapePV1 npts={npts} minterval=10 mult=({', '.join(valores_selecionados)})\n"

# Salvar como arquivo .dss
nome_arquivo = "src/data/13Bus/LoadShapePV.dss"
with open(nome_arquivo, "w") as f:
    f.write(conteudo_dss)

print(f"Processamento concluído!")
print(f"Selecionados {npts} valores dos primeiros {PRIMEIROS_VALORES} (intervalo {INTERVALO})")