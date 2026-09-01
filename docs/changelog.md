# Changelog

Este registro documenta as mudanças significativas do projeto.

---

## [0.1.0] - 2025

### Adicionado

- Co-simulação OpenDSS com mosaik API v3
- Casos de teste IEEE 13, 34 e 123 barras
- Modelo de inversor com cut-in/out, eficiência e prioridade
- Inversor smart com controle IEEE 1547 (Volt-Var, Volt-Watt)
- Modelo de bateria com estados de carga/descarga/idling
- Modelo de regulador de tensão com LDC
- Coletor de dados CSV
- Leitor de séries temporais CSV
- Dockerização dos simuladores
- Exportação de topologia para JSON
- Geração automática de PVSystems (PVCreator)
- Dados reais de 51 estações solares brasileiras
- Validação: co-simulação vs OpenDSS puro com RMSE ~0

### Conhecido

- `base_scenario.py` usa pandapower (legado), não OpenDSS
- `smart_inverter_simulator.py` é shim de compatibilidade
- Testes cobrem apenas modelos de domínio (sem integração)
