# API (Gerada)

Referência gerada automaticamente a partir das docstrings do código-fonte via
[mkdocstrings](https://mkdocstrings.github.io/). Complementa as páginas de
Referência escritas à mão: aquelas priorizam uso e exemplos; estas são a
enumeração exaustiva de assinatura, tipo e docstring de cada membro público,
extraída direto do código — não tem como divergir dele.

## Escopo desta primeira fatia

Cobre os módulos cujas docstrings de **classe e função** já seguem um estilo
estruturado (Google-style, com blocos `Args:`/`Returns:`/`Attributes:`) e
renderizam de forma limpa como Markdown:

- Modelos de domínio: `OpenDSSBattery`, `PVPanelModel`, `VR_Model`
- Wrapper OpenDSS: a classe `OpenDSS` e suas quatro camadas internas
  (`EngineMixin`, `ReaderMixin`, `WriterMixin`, `LegacyReadsMixin`), exibidas
  como membros de `OpenDSS` porque é assim que o próprio wrapper se descreve —
  "a API pública continua plana"
- Inversor inteligente: as classes de `inverter.config` (`ControlConfig`,
  `VoltVarCurve`, `VoltWattCurve`, ...), `SmartInverterModel`, as funções de
  `inverter.opender_factory`, e o modelo legado `InverterModel`

!!! note "Por que documentar a classe, não o módulo"
    Algumas docstrings de **módulo** (`opendss_wrapper.py`, `_legacy.py`,
    `smart_inverter.py`) usam uma tabela em sintaxe reStructuredText (Sphinx)
    como resumo de arquitetura — não renderiza como Markdown. As páginas aqui
    sempre miram a classe ou a função (`::: modulo.Classe`, nunca
    `::: modulo`), o que evita esse conteúdo sem precisar reescrevê-lo — ele
    continua servindo bem quem lê o código-fonte diretamente.

**Fora de escopo, por enquanto:**

- Adaptadores mosaik (`*_sim.py`, `api_opendss.py`, `smart_inverter_simulator.py`,
  `regulator_control.RegulatorSimulator`, etc.) — a superfície pública deles é
  o dict `META` (parâmetros e atributos mosaik), não a assinatura dos métodos
  Python, então uma referência gerada a partir de docstrings não os
  representaria bem. Continuam documentados em
  [Adaptadores Mosaik](../mosaik-adapters.md).
