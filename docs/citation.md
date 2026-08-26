# Citação

O tsre-der-opentes é a plataforma descrita no artigo abaixo, **aceito no Congresso Brasileiro de Automática (CBA) 2026**.

!!! info "Link do artigo"
    Ainda não disponível — o artigo foi aceito, mas os anais do CBA 2026 ainda não foram publicados. Assim que o link estiver disponível, ele substitui esta nota.

## Referência

> SOUZA, L. F. C.; BARROSO, G. C.; MELO, L. S.; SILVA, C. L. N.; LEÃO, R. P. S.; GREGORY, R. C. F.; SAMPAIO, R. F. **Co-simulação de Redes Elétricas Inteligentes: Implementação e Análise de Desempenho da Integração Mosaik-OpenDSS**. Congresso Brasileiro de Automática (CBA), 2026.

**Autores**: Luis Felipe Carneiro de Souza, Giovanni Cordeiro Barroso, Lucas Silveira Melo, Caio Lucas Nascimento Silva, Ruth Pastôra Saraiva Leão, Raquel Cristina Filiagi Gregory, Raimundo Furtado Sampaio — Departamento de Engenharia Elétrica, Universidade Federal do Ceará (UFC).

## Resumo

A integração massiva de recursos energéticos distribuídos (DERs) exige ferramentas de simulação multidisciplinares. Este trabalho propõe uma plataforma de cossimulação utilizando o orquestrador Mosaik e o simulador OpenDSS. A principal contribuição técnica é a integração via biblioteca oficial py-dss-interface operando em modo snapshot, garantindo autonomia para lógicas de controle externas e evitando conflitos com algoritmos internos do simulador. A arquitetura trata dependências cíclicas por meio de conexões time-shifted. A validação no alimentador IEEE 34 barras demonstrou alta precisão, com um erro quadrático médio (RMSE) máximo de 0,00810 p.u. em comparação à execução nativa do OpenDSS. Além disso, o tempo de processamento da rede foi de aproximadamente 3,5 ms por passo. Conclui-se que a plataforma oferece a flexibilidade necessária para validar a operação física e as camadas de controle de redes inteligentes.

**Abstract**: The massive integration of distributed energy resources (DERs) requires multidisciplinary simulation tools. This paper proposes a co-simulation platform utilizing the Mosaik orchestrator and the OpenDSS simulator. The primary technical contribution is the integration via the official py-dss-interface library operating in snapshot mode, ensuring autonomy for external control logic and avoiding conflicts with the simulator's internal algorithms. The architecture addresses cyclic dependencies through time-shifted connections. Validation on the IEEE 34-bus feeder demonstrated high precision, with a maximum Root Mean Square Error (RMSE) of 0.00810 p.u. compared to native OpenDSS execution. Furthermore, network processing time was approximately 3.5 ms per step. It is concluded that the platform provides the necessary flexibility to validate the physical operations and control layers of smart grids.

**Palavras-chave**: Co-simulação; Mosaik; OpenDSS; Redes Inteligentes; Recursos Energéticos Distribuídos.

## BibTeX

```bibtex
@inproceedings{souza2026cosimulacao,
  author    = {Souza, Luis Felipe Carneiro de and Barroso, Giovanni Cordeiro and
               Melo, Lucas Silveira and Silva, Caio Lucas Nascimento and
               Le{\~a}o, Ruth Past{\^o}ra Saraiva and Gregory, Raquel Cristina Filiagi and
               Sampaio, Raimundo Furtado},
  title     = {Co-simula{\c{c}}{\~a}o de Redes El{\'e}tricas Inteligentes: Implementa{\c{c}}{\~a}o
               e An{\'a}lise de Desempenho da Integra{\c{c}}{\~a}o Mosaik-OpenDSS},
  booktitle = {Anais do Congresso Brasileiro de Autom{\'a}tica (CBA)},
  year      = {2026},
  note      = {No prelo}
}
```

Financiamento: Fundação Cearense de Apoio ao Desenvolvimento Científico e Tecnológico (FUNCAP), no âmbito do Programa de Pós-Graduação da Universidade Federal do Ceará.
