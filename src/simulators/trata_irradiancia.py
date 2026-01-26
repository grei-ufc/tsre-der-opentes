import pandas as pd
#import numpy as np

# Read the CSV file
irrad = pd.read_csv("src/data/solar_data_Bremen_minutes.csv")

# Pegar os valores da segunda coluna
valores = (irrad[irrad.columns[1]].values)/1000

# Quantidade total de itens
npts = len(valores) 

valores_limpos = []
for v in valores:
    if pd.isna(v):
        valores_limpos.append('0.00000')  
    else:
        valores_limpos.append(f"{v:.5f}")

# Converter para string com vírgulas
linha_unica = ', '.join(str(v) for v in valores)

# Criar a string no formato DSS
conteudo_dss = f"New LoadShape.MyShapePV1 npts={npts} sinterval=1 mult=({', '.join(valores_limpos)})\n"

# Salvar como arquivo .dss
nome_arquivo = "src/data/13Bus/LoadShapePV.dss"
with open(nome_arquivo, "w") as f:
    f.write(conteudo_dss)
    