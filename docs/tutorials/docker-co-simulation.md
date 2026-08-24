# Co-Simulação Docker

Este tutorial guia a execução completa de um cenário via Docker, onde cada simulador roda em seu próprio container.

## Objetivo

Executar o cenário IEEE 123-bus com PV usando Docker e gerar o arquivo de resultados.

## Pré-requisitos

- Docker e Docker Compose instalados ([Instalação](../getting-started/installation.md))
- Repositório clonado
- uv instalado

## Arquitetura Docker

```
┌─────────────────────────────────────────────────────────────────┐
│ Host Windows/Linux                                               │
│                                                                  │
│  cenariodocker.py ──── localhost:5671 ──> opendss (container)   │
│       │              ──── localhost:5678 ──> pv-panel (container)│
│       │              ──── localhost:5677 ──> inverter (container)│
│       │              ──── localhost:5675 ──> csv-1 (container)   │
│       │              ──── localhost:5676 ──> csv-2 (container)   │
│       │              ──── localhost:5673 ──> collector (container)│
│       │                                                          │
│       └──> output/result_run_ieee123_cosim_pv_5min.csv          │
└─────────────────────────────────────────────────────────────────┘
```

Cada container:

1. Sobe com `python -m <modulo> --remote 0.0.0.0:<porta>`
2. Abre um servidor TCP aguardando conexão do mosaik
3. Executa a simulação quando o cenário conecta

## Passo a passo

### 1. Construir a imagem

```bash
docker build -t opentes-simulador .
```

Isso cria a imagem `opentes-simulador` baseada em `python:3.12-slim`.

### 2. Subir os containers

```bash
docker compose up -d
```

Verifique que todos estão rodando:

```bash
docker compose ps
```

Todos os serviços devem mostrar status `Up`.

### 3. Executar o cenário

Em outro terminal:

```bash
uv run --no-sync python scenarios/cenariodocker.py
```

### 4. Monitorar a execução

Para ver os logs de um container específico:

```bash
docker compose logs -f opendss
docker compose logs -f collector
```

### 5. Verificar resultados

O arquivo de saída estará em:

```
output/result_run_ieee123_cosim_pv_5min.csv
```

### 6. Parar os containers

```bash
docker compose down
```

## Cenário Docker smart inverter

Para o cenário com inversor smart (13-bus):

```bash
uv run --no-sync python scenarios/scenario_13bus_smart_pv_docker.py
```

Este cenário usa a porta 5680 (smart-inverter) em vez de 5677 (inverter-std).

## Solução de problemas

### Container sai com código 0

Verifique se o entrypoint está correto no `docker-compose.yml`. O serviço `opendss` deve executar `simulators.opendss.api_opendss` com `--remote`.

### Cenário não conecta

1. Verifique se os containers estão rodando: `docker compose ps`
2. Verifique as portas: `netstat -an | findstr 5671`
3. Execute o cenário **depois** que os containers estiverem `Up`

### Resultado não aparece no host

Confirme se o volume `./output:/app/output` está montado no serviço `collector`.

### Erro de permissão no volume

No Linux, pode ser necessário:

```bash
sudo chown -R $USER:$USER output/
```

Consulte [Dockerização dos Simuladores](../how-to-guides/deploy-with-docker.md) para mais detalhes.
