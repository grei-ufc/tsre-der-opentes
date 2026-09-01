# Decisões de Projeto

## Wrapper único para OpenDSS

**Decisão**: `opendss_wrapper.py` é a única interface com `py_dss_interface`.

**Motivo**: Centraliza a interação com o motor OpenDSS, facilitando manutenção e evitando chamadas inconsistentes ao DSS em diferentes partes do código.

**Trade-off**: Todas as operações passam pelo wrapper, mesmo as simples. Isso adiciona uma camada de indireção, mas garante consistência.

## API v3 do mosaik

**Decisão**: Todos os adaptadores usam `mosaik_api_v3` com `api_version: '3.0'`.

**Motivo**: A versão 3 é a atual do mosaik. Adaptadores em v2 foram migrados durante a refatoração.

**Trade-off**: Cenários legados que ainda referenciam módulos antigos precisam ser atualizados.

## Containers Docker por simulador

**Decisão**: Cada adaptador roda em um container Docker separado, com porta TCP fixa.

**Motivo**: Permite escalar simuladores independentemente, isola falhas e facilita deploy distribuído.

**Trade-off**: Adiciona overhead de rede para cada passo de simulação. Para cenários pequenos, o modo local é mais eficiente.

## Portas fixas (5671–5680)

**Decisão**: Cada tipo de simulador tem uma porta TCP fixa.

**Motivo**: Simplifica a configuração do `docker-compose.yml` e do `SIM_CONFIG` nos cenários.

**Trade-off**: Não é possível rodar dois containers do mesmo tipo simultaneamente sem ajustar portas.

## Inversão de sinais na fronteira

**Decisão**: O OpenDSS retorna geração negativa; a inversão acontece em `extract_3phase_pq(sign=-1)`.

**Motivo**: Mantém a convenção do OpenDSS inalterada internamente, e presenta valores intuitivos (positivos para geração) aos demais módulos.

**Trade-off**: Quem lê código precisa entender onde a inversão ocorre.

## Cenários como scripts independentes

**Decisão**: Cada cenário é um script standalone em `scenarios/`, não um módulo importável.

**Motivo**: Cenário define sua própria configuração, fluxo e parâmetros. Pode ser executado diretamente sem importações complexas.

**Trade-off**: Há duplicação entre cenários similares (ex: `cenariodocker.py` vs `opendss_scenario_123bus_pv.py`).

## Um objeto OpenDER por PVSystem

**Decisão**: Cada `PVSystem` do circuito vira uma `InverterUnit` com seu próprio
objeto OpenDER — trifásico (`NP_PHASE="THREE"`) ou monofásico
(`NP_PHASE="SINGLE"`), conforme o elemento. Uma entidade mosaik `Inverter`
agrega até três unidades da mesma barra.

**Motivo**: É como o IEEE 1547 modela um inversor: cada um mede a tensão do
próprio terminal e responde por conta própria. A modelagem anterior — três
objetos *trifásicos* de kVA/3, cada um alimentado com a tensão de uma fase como
se fosse equilibrada — não tinha lastro físico, e um DER trifásico do OpenDER
devolve P/Q **totais**, nunca por fase (em operação normal a corrente de
sequência negativa é zero, então "por fase" seria sempre total/3).

**Trade-off**: Mais objetos OpenDER por barra. Em contrapartida, a injeção
monofásica é real e roteável de volta para cada `PVSystem`.

## Configuração de controle declarativa e validada

**Decisão**: As curvas e o modo de controle são dataclasses validadas
(`simulators.inverter.config`), traduzidas para o `DERCommonFileFormat` em um
único lugar (`opender_factory`).

**Motivo**: Os setters do OpenDER apenas *avisam* (`logging.warning`) quando um
ajuste está fora da faixa da norma, e nunca falham. Num alimentador com dezenas
de inversores, o aviso se perde e o que sobra é um fluxo de potência
silenciosamente errado. Erro estrutural agora levanta `ConfigError` na
construção do cenário.

**Motivo (segundo)**: O modo de reativo é um `enum`, não um conjunto de flags,
porque o OpenDER resolve os quatro modos por prioridade fixa — habilitar
fator de potência constante junto com volt-var desliga o volt-var em silêncio.

## Placa montada de uma vez, nunca mutada

**Decisão**: O `DERCommonFileFormat` é construído completo e passado ao
construtor do DER. Nada é ajustado depois.

**Motivo**: O setter de `NP_VA_MAX` reexecuta a inicialização da curva de
capacidade reativa usando o `NP_Q_MAX_INJ` corrente. Ajustar só a potência de um
DER já construído deixava a capacidade travada no valor de fábrica (44 kvar),
independentemente do tamanho do inversor. `opender_factory.build_der` confere a
curva resultante antes de devolver o objeto — é uma guarda de regressão, não
uma verificação decorativa.

## Um adaptador de inversor

**Decisão**: `smart_inverter_simulator.py` é o único adaptador; com ou sem
funções de rede. `inverter_simulator.py` é um shim.

**Motivo**: Havia três adaptadores expondo fatias parciais e disjuntas do mesmo
modelo — nenhum expunha a superfície completa. A `META` agora é derivada dos
registros de entrada e saída, como em `opendss/element_specs.py`, de modo que um
atributo não pode ser declarado sem o código que o implementa.

## Dados de estações solares reais

**Decisão**: O projeto inclui dados reais de 51 estações solares brasileiras em `data/InfoPV/`.

**Motivo**: Permite validação com dados reais e suporta cenários realistas.

**Trade-off**: Aumenta o tamanho do repositório. Os dados estão versionados no Git junto com o restante do código (`data/`), não em um repositório ou storage separado.
