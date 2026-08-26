# Manual para Simulação de um Novo Cenário e Topologia

Este manual descreve o passo a passo necessário para incluir e rodar uma nova topologia de rede (arquivos OpenDSS) no ambiente de co-simulação (Mosaik) deste projeto.

## 1. Organização dos Arquivos OpenDSS

O primeiro passo é adicionar os arquivos do OpenDSS referentes à nova rede elétrica no projeto.

1. Navegue até a pasta de dados: `src/data/`.
2. Crie uma nova pasta com o nome da sua topologia (ex: `src/data/NovaRede`).
3. Coloque **todos** os arquivos do OpenDSS da sua simulação dentro dessa nova pasta (arquivos `.dss`, arquivos de curvas de carga em `.csv` ou `.txt`, etc.).
4. Identifique o arquivo principal da simulação (o arquivo *master* que faz o `clear` e instancia o circuito).

> [!TIP]
> Se a sua simulação utiliza dados temporais (irradiância, temperatura, curvas de carga), garanta que os arquivos de dados estejam na mesma pasta e que os caminhos relativos dentro do seu arquivo `.dss` estejam corretos em relação a essa pasta.

## 2. Criação do Script de Cenário

Os cenários são os scripts Python que orquestram a co-simulação através do Mosaik. 

1. Acesse a pasta `src/scenarios/`.
2. Crie um novo arquivo Python para o seu cenário (ex: `novo_cenario.py`).
3. **Dica:** É mais fácil copiar um cenário existente (como `opendss_scenario_123bus.py` para rodar local, ou `cenariodocker.py` para rodar via Docker) e adaptá-lo.

## 3. Ajuste de Caminhos no Script

Abra o seu script de cenário recém-criado e altere as variáveis que apontam para os arquivos de dados.

### Se for rodar localmente (sem Docker):
Modifique as variáveis que apontam para os caminhos:
```python
# Aponte para a pasta criada no Passo 1
DATA_DIR = PROJECT_ROOT / "data" / "NovaRede"

# Aponte para o arquivo principal do OpenDSS
CIRCUITO_DSS = DATA_DIR / "arquivo_principal.dss"

# Defina o nome do arquivo de saída de resultados
ARQUIVO_RESULTADOS_CSV = OUTPUT_DIR / 'resultado_novarede.csv'
```

### Se for rodar via Docker:
Você precisará lidar com dois mapeamentos de caminhos (o do seu sistema e o interno do contêiner Docker):
```python
# Caminhos no seu computador (Host)
DATA_DIR_HOST = PROJECT_ROOT / "data" / "NovaRede"
CIRCUITO_DSS_HOST = DATA_DIR_HOST / "arquivo_principal.dss"
ARQUIVO_RESULTADOS_CSV_HOST = OUTPUT_DIR_HOST / 'resultado_novarede.csv'

# Caminhos no Contêiner (Linux)
# IMPORTANTE: O Docker mapeia a pasta 'src' do host para '/app/src' no contêiner
CONTAINER_DATA = "/app/src/data/NovaRede"
CIRCUITO_DSS_CONT = f"{CONTAINER_DATA}/arquivo_principal.dss"
ARQUIVO_RESULTADOS_CSV_CONT = "/app/output/resultado_novarede.csv"
```

## 4. Configuração dos Monitores na Co-Simulação

O script Mosaik conecta o simulador do OpenDSS ao Coletor de Dados (`Collector`). É fundamental atualizar o script para monitorar as barras e linhas que **realmente existem** na sua nova topologia.

Localize o trecho de código que monitora elementos da rede e altere os nomes:
```python
# Exemplo de como monitorar barras específicas da sua nova rede
target_names = ['nome_barra_1', 'nome_barra_2']

for target_name in target_names:
    target_eid = f'Bus-{target_name}' # O sufixo Bus- é padrão do simulador OpenDSS
    bus_entities = [e for e in grid.children if e.eid == target_eid]
    if bus_entities:
        world.connect(bus_entities[0], monitor, 'V1_pu', 'V2_pu', 'V3_pu')

# Exemplo para Linhas (verifique se os nomes batem com o seu .dss)
target_name = 'nome_da_linha'
target_eid = f'Line-{target_name}'
line_entities = [e for e in grid.children if e.eid.lower() == target_eid.lower()]
if line_entities:
    world.connect(line_entities[0], monitor, 'I1_A', 'P1_w')
```
> [!WARNING]
> Se você tentar monitorar uma barra (ex: `Bus-149`) que não existe na nova rede (como copiando o código da 123Bus sem alterar), os dados não serão extraídos para essa entidade.

## 5. Parâmetros da Simulação (Tempo e Passos)

Defina a duração e os passos (steps) de tempo da sua simulação conforme os perfis usados nos seus arquivos `.dss` (por exemplo, se usa curva de carga diária, perfis anuais, etc):
```python
START_DATE = "2024-01-01 00:00:00"
STEP_SIZE = 60 * 5  # Ex: 5 minutos
N_PASSOS = 288      # Número total de passos que serão rodados
END_TIME = N_PASSOS * STEP_SIZE
```

## 6. Execução do Novo Cenário

Após configurar e salvar o script `novo_cenario.py`, você pode executá-lo.

**Para rodar via ambiente local (usando `uv`):**
No terminal, certifique-se de estar na raiz do projeto e execute:
```bash
uv run --no-sync python src/scenarios/novo_cenario.py
```

**Para rodar via Docker (caso tenha usado a abordagem do `cenariodocker.py`):**
Primeiro, suba os serviços dos simuladores:
```bash
docker compose up -d
```
Em seguida, rode o script do seu cenário (o cenário é o maestro que vai conversar com os contêineres pela rede interna usando localhost):
```bash
uv run --no-sync python src/scenarios/novo_cenario.py
```

Após a conclusão da simulação, os resultados estrão disponíveis na pasta `output/` conforme definido no script.
