# tsre-der-opentes

**Simulação co-simulada de recursos energéticos distribuídos em redes de distribuição**

tsre-der-opentes é um projeto open source que utiliza o framework [mosaik](https://mosaik.readthedocs.io/) para realizar co-simulação de sistemas de distribuição de energia elétrica com recursos energéticos distribuídos (DER) — sistemas fotovoltaicos, inversores inteligentes, armazenamento e reguladores de tensão.

O motor de fluxo de potência é o [OpenDSS](https://www.epri.com/pages/sa/opendss), acessado via [py-dss-interface](https://github.com/PauloRadatz/py_dss_interface).

## O que o projeto permite

- Simular sistemas fotovoltaicos com modelos de irradiância e temperatura
- Testar inversores com controle IEEE 1547 (Volt-Var, Volt-Watt, fator de potência fixo)
- Simular armazenamento de energia (baterias) com estados de carga/descarga/idling
- Controlar reguladores de tensão com compensação de queda de linha
- Executar cenários localmente ou em containers Docker
- Coletar resultados em CSV para análise
- Validar co-simulação contra OpenDSS puro com erros praticamente nulos

## Casos de teste suportados

| Caso IEEE | Barras | Status |
|---|---|---|
| IEEE 13-Node | 13 | Completo (PV, smart inverter, Docker) |
| IEEE 34-Node | 34 | Completo (regulador de tensão) |
| IEEE 123-Node | 123 | Completo (PV, smart inverter, Docker, validação) |
| LV-rural (SimBench) | Variável | Legado (pandapower, não OpenDSS) |

## Início rápido

```bash
# Instalar dependências
uv sync

# Rodar a primeira simulação (100% Python, sem Docker)
uv run --no-sync python scenarios/opendss_scenario.py
```

Consulte [Primeira Simulação](getting-started/first-simulation.md) para o passo a passo completo, ou [Instalação](getting-started/installation.md) para detalhes do ambiente. O modo Docker — recomendado para cenários completos com múltiplos simuladores — está em [Co-Simulação Docker](tutorials/docker-co-simulation.md).

## Publicação

Este projeto é descrito em um artigo aceito no Congresso Brasileiro de Automática (CBA) 2026. Veja [Citação](citation.md) para a referência completa, resumo e BibTeX.

## Licença

MIT License — Smart Grids Research Group - UFC (Universidade Federal do Ceará), 2025
