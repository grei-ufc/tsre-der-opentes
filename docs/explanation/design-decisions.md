# Decisões de Projeto

## Wrapper único para OpenDSS (fachada)

**Decisão**: `opendss_wrapper.py` é a única interface com `py_dss_interface` —
o padrão de projeto *Fachada* (Gamma et al., 1994). O adaptador e o registry
pedem tudo a ela por métodos nomeados; os módulos por dispositivo ficam atrás
dela.

**Motivo**: Centraliza a interação com o motor OpenDSS. As regras que a
fachada aplica — detecção de erro pelo código do motor, invalidação do cache,
contorno das peculiaridades da biblioteca (a lista `['None']` para classe vazia,
o `error_desc` que derruba o processo) — valem em um lugar só, e uma mudança na
biblioteca se resolve ali.

**Verificação**: enquanto a regra era só texto, seis pontos do adaptador
passaram por cima dela. Hoje `tests/test_wrapper_layers.py::TestFacadeIsNotBypassed`
analisa o código e falha se o adaptador ou o registry acessarem
`dss_wrapper.dss`, ou se algum simulador fora do pacote `opendss` importar o
`py_dss_interface`.

**Trade-off**: Todas as operações passam pelo wrapper, mesmo as simples. Isso adiciona uma camada de indireção, mas garante consistência.

## API v3 do mosaik

**Decisão**: Todos os adaptadores usam `mosaik_api_v3` com `api_version: '3.0'`.

**Motivo**: A versão 3 é a atual do mosaik. Adaptadores em v2 foram migrados durante a refatoração.

**Trade-off**: Cenários legados que ainda referenciam módulos antigos precisam ser atualizados.

## Containers Docker por simulador

**Decisão**: Cada adaptador roda em um container Docker separado, com porta TCP fixa.

**Motivo**: Permite escalar simuladores independentemente, isola falhas e facilita deploy distribuído.

**Trade-off**: Adiciona overhead de rede para cada passo de simulação. Para cenários pequenos, o modo local é mais eficiente.

## Portas fixas (5771–5780)

**Decisão**: Cada tipo de simulador tem uma porta TCP fixa, na faixa 5771–5780.

**Motivo**: Simplifica a configuração do `docker-compose.yml` e do `SIM_CONFIG`
nos cenários. A faixa era 5671–5680 e foi movida porque, no Windows, o WinNAT e
o Hyper-V reservam faixas de portas de forma aleatória, o que travava a
inicialização dos contêineres e corrompia as conexões.

**Trade-off**: Não é possível rodar dois containers do mesmo tipo simultaneamente sem ajustar portas.

## Inversão de sinais na fronteira

**Decisão**: O OpenDSS retorna geração negativa; a inversão acontece no registry, pelo `sign=-1` do `phase_attr_map` de PVSystem, Storage e Generator.

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

## A potência comandada é a entregue

**Decisão**: Ao compilar o circuito, o wrapper troca a conversão DC/AC de todo
PVSystem por uma ideal (curvas de eficiência e de temperatura planas,
`%cutin`/`%cutout` de 0,0001) e abre a faixa `Vminpu`/`Vmaxpu` de todo Generator
(0,001–10 pu). Não há opção para desligar.

**Motivo**: Na co-simulação, a potência chega ao OpenDSS já calculada — pelo
inversor modelado em outro simulador, ou por uma curva. O modelo nativo do
PVSystem ainda a multiplicaria pela eficiência e pelo derating térmico e
desligaria o inversor abaixo de 20 % do kVA; fora da faixa de tensão, o
Generator vira impedância constante (medido: 100 kW comandados a 0,97 pu, com
`Vminpu=0.99`, saíam 96 kW). Em ambos os casos a injeção sairia diferente da
comandada, sem nada avisando.

**Trade-off**: Quem quiser as perdas de conversão as modela fora do OpenDSS. As
curvas, os limiares e a faixa declarados no `.dss` continuam no `extra_info`,
para isso.

## Taps só por controlador externo

**Decisão**: O controle automático de todo RegControl é travado ao compilar
(`MaxTapChange=0`), antes da primeira solução, sem mexer na posição do tap. O
tap declarado no `.dss` vale até um controlador externo comandá-lo pelo
atributo `tap`.

**Motivo**: A regulação de tensão é objeto de estudo — os controladores ficam
em Python, fora do motor. Com o controle nativo ativo, os dois disputariam o
tap. Antes, o travamento ficava numa função de leitura chamada na criação das
entidades, que além disso zerava os taps, e a solução do construtor ainda saía
com o controle nativo agindo.

**Trade-off**: Um cenário sem controlador de tap roda com os taps fixos na
posição declarada. O controlador externo precisa ser iniciado com o tap real
(`tap_ini=info["tap_ini"]`), porque envia a própria posição a cada passo.

## Falhar alto, com saída para "seguir e marcar"

**Decisão**: Erros do motor — comando recusado, fluxo que não convergiu —
interrompem a simulação por padrão. O parâmetro `fail_on_error=False` do
`init()` troca a interrupção por uma mensagem, e o estado de cada passo fica no
atributo `converged` do modelo `Circuit`. Erros de uso (elemento ou propriedade
inexistente, multiplicador fora da faixa) interrompem sempre.

**Motivo**: Numa co-simulação, uma falha silenciosa produz um dia inteiro de
dados sutilmente errados, sem nada no resultado que a denuncie. Quem prefere
não perder a execução inteira por um passo ruim tem um caminho explícito, e o
resultado registra quais instantes não podem ser levados a sério.

## Caixas de diálogo só na compilação; erro pelo código do motor

**Decisão**: As caixas de diálogo do OpenDSS (`AllowForms`) ficam ligadas só
enquanto um `.dss` compila. Fora disso, o `run_command` detecta o erro pelo
código que o motor registra (`errorinterface.error_code`), e não pela palavra
"error" no texto.

**Motivo**: No Windows, a caixa trava a execução até alguém clicar, com ou sem
`fail_on_error`. Desligá-la de vez, porém, silenciaria erros de digitação no
meio de um `.dss`: o `Redirect` informa só o erro da última linha executada. E a
maioria das mensagens de erro do motor não contém a palavra "error" —
`Unknown parameter` (580), `Unknown Command` (302), `... not found` (180)
passavam como aviso.

**Trade-off**: Um erro no `.dss` ao carregar ainda espera um clique — numa
execução sem ninguém olhando, no Windows, ela fica parada ali.

## Resumir a barra fica com quem consome

**Decisão**: O modelo `Bus` expõe só as tensões e os ângulos por fase. Os
agregados (`V_min_pu`, `V_max_pu`, `V_mean_pu`, `V_unb_pct`) foram removidos.

**Motivo**: Nasceram para colorir o mapa de calor da visualização, mas ela
passou a reduzir as três fases por conta própria, e nada mais os consumia. A
fase ausente é `NaN`, então qualquer redução precisa ignorá-la — o que
`numpy.nanmin`/`nanmean` já fazem.

## Dados de estações solares reais

**Decisão**: O projeto inclui dados reais de 51 estações solares brasileiras em `data/InfoPV/`.

**Motivo**: Permite validação com dados reais e suporta cenários realistas.

**Trade-off**: Aumenta o tamanho do repositório. Os dados estão versionados no Git junto com o restante do código (`data/`), não em um repositório ou storage separado.
