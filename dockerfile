# Passo 1: Usar a imagem base do Python 3.12 (versão slim)
FROM python:3.12-slim

# Passo 2: Instalar dependências do sistema necessárias para compilação
# Trocamos 'libgl1-mesa-glx' por 'libgl1', que é o nome correto nas versões novas
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Passo 3: Definir o diretório de trabalho
WORKDIR /app

# Passo 4: Copiar e instalar as dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Passo 5: Copiar os códigos e dados
COPY src/ ./src/

# Passo 6: Configurar o PYTHONPATH para os módulos se encontrarem
ENV PYTHONPATH=/app/src