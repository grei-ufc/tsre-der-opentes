git add .gitignore
git commit -m "chore: atualizar .gitignore com novos arquivos ignorados"

git add pyproject.toml
git commit -m "chore: atualizar dependencias no pyproject.toml"

git add uv.lock
git commit -m "chore: sincronizar lockfile uv.lock"

git add AGENTS.md
git commit -m "docs: adicionar doc AGENTS.md com regras do projeto"

git add docs/how-to-guides/plano.md
git commit -m "docs: adicionar plano de refatoracao detalhado"

git add output/topologia_exportada.json
git commit -m "chore: adicionar arquivo de exemplo topologia_exportada.json"

git add src/output/result_run_ieee123_cosim_pv_5min.csv
git commit -m "chore: salvar resultado de simulacao no arquivo csv"

git add src/output/topologia_ieee123_cosim_pv_5min.json
git commit -m "chore: salvar topologia gerada para ieee123 no formato json"

git add src/simulators/battery_model.py src/simulators/battery/battery_model.py src/simulators/battery/__init__.py
git commit -m "refactor(battery): isolar modulo battery_model em subpacote"

git add src/simulators/battery_sim.py src/simulators/battery/battery_sim.py
git commit -m "refactor(battery): isolar modulo battery_sim e atualizar API mosaik"

git add src/simulators/collector.py src/simulators/collector/collector.py src/simulators/collector/__init__.py
git commit -m "refactor(collector): mover collector_sim para subpacote e migrar API"

git add src/simulators/csv_sim_pandas.py src/simulators/collector/csv_sim_pandas.py
git commit -m "refactor(collector): mover csv_sim_pandas para subpacote collector"

git add src/simulators/controller_sim.py src/simulators/controller/controller_sim.py src/simulators/controller/__init__.py
git commit -m "refactor(controller): isolar controller_sim em novo subpacote"

git add src/simulators/regulator_control.py src/simulators/controller/regulator_control.py
git commit -m "refactor(controller): mover regulator_control para o diretorio de controladores"

git add src/simulators/inverter_simulator.py src/simulators/smart_inverter_simulator.py src/simulators/smart_inverter_simulator_2.py src/simulators/inverter/
git commit -m "refactor(inverter): consolidar simuladores de inversor e criar novo InverterModel"

git add src/simulators/opendss_simulator.py src/simulators/old/opendss_simulator.py
git commit -m "refactor(opendss): aposentar shim opendss_simulator enviando para pasta old"

git add src/simulators/api_opendss.py src/simulators/opendss/api_opendss.py src/simulators/opendss/__init__.py
git commit -m "refactor(opendss): mover wrapper api_opendss e simplificar get_data"

git add src/simulators/graph_model.py src/simulators/opendss/graph_model.py
git commit -m "refactor(opendss): migrar domain models para dentro do modulo opendss"

git add src/simulators/topology_builder.py src/simulators/opendss/topology_builder.py
git commit -m "refactor(opendss): mover logic de gravo (topology_builder) para diretorio especifico"

git add src/simulators/opendss_wrapper.py src/simulators/opendss/opendss_wrapper.py
git commit -m "refactor(opendss): enxugar opendss_wrapper delegando funcoes isoladas"

git add src/simulators/opendss/_utils.py src/simulators/opendss/opendss_pv.py src/simulators/opendss/opendss_regulator.py src/simulators/opendss/opendss_storage.py
git commit -m "feat(opendss): adicionar metodos de extracao (pv, storage, regulator, utils)"

git add src/simulators/pv_panel_simulator.py src/simulators/pv/
git commit -m "refactor(pv): criar subpacote pv e mover pv_panel_simulator"

git add src/scenarios/base_scenario.py
git commit -m "refactor(scenarios): melhorar a flexibilidade da pipeline do base_scenario"

git add src/scenarios/opendss_scenario.py
git commit -m "refactor(scenarios): ajustar referencias no opendss_scenario principal"

git add src/scenarios/opendss_scenario_123bus.py
git commit -m "refactor(scenarios): refinar pathing no opendss_scenario_123bus"

git add src/scenarios/opendss_scenario_123bus_pv.py
git commit -m "refactor(scenarios): aplicar novos modulos helper em opendss_scenario_123bus_pv"

git add src/scenarios/opendss_scenario_123bus_smart_pv.py
git commit -m "refactor(scenarios): adequar caminhos no opendss_scenario_123bus_smart_pv"

git add src/scenarios/opendss_scenario_34bus.py
git commit -m "refactor(scenarios): corrigir imports da nova estrutura em 34bus"

git add src/scenarios/opendss_scenario_pv.py
git commit -m "refactor(scenarios): consolidar implementacao no opendss_scenario_pv"

git add src/scenarios/opendss_scenario_123bus_pv_export_json.py
git commit -m "feat(scenarios): criar cenario novo opendss_scenario_123bus_pv_export_json"

git add src/simulators/topologia.py
git commit -m "refactor(simulators): aprimorar formatacao em script topologia"

git add .
git commit -m "chore: comitar arquivos residuais do processo de refatoracao"
