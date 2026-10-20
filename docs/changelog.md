# Changelog

Este registro documenta as mudanças significativas do projeto. Itens marcados
com ⚠ quebram compatibilidade com cenários ou dados anteriores.

---

## [Não publicado]

### Adicionado

- Elemento `Generator` no adaptador OpenDSS: entidade `Generator-<nome>`,
  despacho por `P_set`/`Q_set` ou `P_mult`, curva `daily`/`yearly` do `.dss`
  seguida a cada passo, e presença na topologia exportada
  (`element_type="generator"`)
- Curvas de multiplicadores: `S_mult` na carga e `P_mult` no PV, na bateria e no
  gerador, com a faixa conferida a cada passo
- Parâmetros do `init()` do adaptador: `buscoords`, `tolerance`,
  `max_iterations` e `fail_on_error`
- Modelo `Circuit`, com `converged`, `iterations` e os totais do alimentador a
  cada passo
- Modelo `Switch`: chaves separadas das linhas, com `is_open` como entrada e
  saída
- Perdas por elemento em linhas e transformadores (`Ploss_kw`, `Ploss1_kw`...)
  e carregamento por fase das linhas (`Loading1_pct`...)
- Geração do PV em pu da placa do inversor (`P_pu`, `P1_pu`...)
- Visualização da rede no navegador (`webvis`) e os cenários `*_web.py`
- Topologia em JSON com os elementos ligados a cada barra (`elements`,
  `metadata.attached`) e coordenada ausente como `null`
- Inversor inteligente reescrito sobre o OpenDER (IEEE 1547), com configuração
  declarativa e validada
- Métodos da fachada `load_buscoords`, `get_circuit_summary`,
  `get_solution_state`, `get_all_buses_info` e `get_loadshape`; `grafo_tsdq`
  passa a devolver o grafo
- Teste de arquitetura (`TestFacadeIsNotBypassed`) que impede o acesso ao motor
  por cima da fachada

### Alterado

- ⚠ A conversão DC/AC dos PVSystems é sempre ideal, aplicada ao compilar o
  circuito; o parâmetro `bypass_native_pv_curves` deixou de existir
- ⚠ O eid do PVSystem perdeu o sufixo da barra: `PVSystem-pv`, e não
  `PVSystem-pv_bus634`
- ⚠ O modelo `Bus` expõe só as tensões e os ângulos por fase
- ⚠ As portas dos simuladores no Docker passaram de 5671–5680 para 5771–5780
- ⚠ Fase ausente é `NaN`, e não zero; no CSV, célula vazia
- O controle automático dos reguladores é travado ao compilar, sem mexer no
  tap; `tap_ini` reporta o tap declarado, e os cenários iniciam o controlador
  externo nele
- A faixa `Vminpu`/`Vmaxpu` dos Generators é aberta ao compilar
- Erros do motor detectados pelo código do OpenDSS; caixas de diálogo ligadas
  só durante a compilação
- `set_power` atende só Load, Generator e Storage, e recusa PVSystem
- `util/topologia.py` exporta pela fachada
- O `metadata.attached` de toda barra no JSON da topologia ganhou a chave
  `generator`
- No adaptador, `profiles` substitui `loads_with_profiles`

### Removido

- O parâmetro `bypass_native_pv_curves`, o atributo `includes_elements` e o
  `storage_names` do wrapper
- Os atributos `V_min_pu`, `V_max_pu`, `V_mean_pu` e `V_unb_pct` da barra
- A camada de leituras legadas do wrapper

### Corrigido

- O coletor grava o CSV por nome de coluna, e não por posição
- A convergência de cada solução é conferida
- Uma LoadShape inexistente era lida como a curva anterior; uma vazia faria o
  passo dividir por zero. As duas são recusadas
- O controle nativo dos reguladores agia na solução do construtor, e os taps
  declarados eram zerados na criação das entidades
- O `fail_on_error` passado ao `world.start` era ignorado
- Comandos recusados pelo motor (`Unknown parameter`, `Unknown Command`, `...
  not found`) passavam como aviso
- `cenariodocker.py` e `scenario_13bus_smart_pv_docker.py` conectavam nas
  portas antigas

### Conhecido

- O `setup_done()` gasta um passo de energia das baterias declaradas
  carregando ou descarregando
- Na bateria, um `Q_set` sem `P_set` é descartado sem aviso
- Curvas com pontos por hora explícitos (`interval=0`) são tratadas como
  igualmente espaçadas no passo da simulação
- `Edit` num elemento inexistente é silencioso no próprio motor, e o conteúdo
  de um arquivo de coordenadas não é conferido
- O `docker build` exige a pasta `output/`; o `requirements.txt` do Docker não
  fixa a versão do `py-dss-interface` (o `uv.lock` fixa a 2.3.0); o caminho
  Docker/Linux não é exercitado pela CI

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
