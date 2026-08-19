Plano Completo de Refatoração
Fase 1: Correções Fundamentais (sem quebrar nada)
#	Mudança
1.1	Migrar battery_sim.py de mosaik_api → mosaik_api_v3 e adicionar api_version: '3.0' ao META
1.2	Migrar controller_sim.py de mosaik_api → mosaik_api_v3
1.3	Migrar collector.py de mosaik_api → mosaik_api_v3
1.4	Migrar csv_sim_pandas.py de mosaik_api → mosaik_api_v3
1.5	Substituir except: por except Exception: nos pontos críticos
Fase 2: Eliminar Duplicação nos Simuladores
#	Mudança
2.1	Criar simulators/_utils.py com funções helper: _normalize_phase_list(), _build_phase_mapping(), _extract_3phase_pq()
2.2	Simplificar get_data() em api_opendss.py usando os helpers (remove ~100 linhas duplicadas)
2.3	Unificar InverterModel — criar simulators/models/inverter.py com a versão completa (com OpenDER + cut-in/out + prioridade)
2.4	Fazer inverter_simulator.py e smart_inverter_simulator_2.py importarem do models/inverter.py
2.5	Remover smart_inverter_simulator.py (versão antiga do InverterModel com API do OpenDER diferente)
Fase 3: Separar Responsabilidades do Wrapper
#	Mudança
3.1	Extrair métodos de PV info → simulators/opendss_pv.py (funções get_all_pvsystems_info, set_pvsystem_pq, get_pvsystem_power)
3.2	Extrair métodos de Storage info → simulators/opendss_storage.py (get_all_storages_info)
3.3	Extrair métodos de Regulator info → simulators/opendss_regulator.py (get_all_regulators_info, get_regulator_measurements)
3.4	Manter opendss_wrapper.py apenas com operações fundamentais de circuito (compile, solve, get/set voltage/power/current)
3.5	api_opendss.py importa dos novos módulos de forma composta
Fase 4: Organização e Infraestrutura
#	Mudança
4.1	Criar simulators/__init__.py com exports organizados
4.2	Adicionar logging em vez de print() nos módulos principais
4.3	Extrair constantes mágicas para simulators/constants.py (SECONDS_PER_DAY = 86400, PV_POWER_THRESHOLD = 0.001, etc.)
4.4	Adicionar type hints nos signatures públicos dos módulos core
Fase 5: Simplificação dos Cenários
#	Mudança
5.1	Criar scenarios/_base.py com funções helper: setup_simulators(), create_pv_chain(), monitor_buses(), monitor_lines()
5.2	Refatorar cenariodocker.py para usar helpers (reduz de ~170 para ~80 linhas)
5.3	Refatorar opendss_scenario_123bus_pv.py para usar helpers
5.4	Manter cenários legados (opendss_scenario.py, _34bus.py, etc.) intactos para não quebrar fluxos existentes
Fase 6: Limpeza Final
#	Mudança
6.1	Remover opendss_simulator.py (shim de 20 linhas que só faz re-export)
6.2	Remover topologia.py (script standalone, não é módulo)
6.3	Remover smart_inverter_simulator_2.py se Fase 2.4 consolidou tudo
6.4	Remover código comentado extenso (blocos de 20+ linhas em opendss_wrapper.py)
6.5	Atualizar pyproject.toml description
Resultado Esperado
Antes: 18 arquivos em simulators/, ~4.500 linhas, duplicação significativa, API v2/v3 misturada, sem logging.
Depois: ~14 arquivos organizados, 3.200 linhas (redução de 30%), API unificada em v3, helpers reutilizáveis, cenários simplificados.