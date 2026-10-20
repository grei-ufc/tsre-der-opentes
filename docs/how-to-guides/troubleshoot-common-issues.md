# Solução de Problemas Comuns

## Erros de importação

### `ModuleNotFoundError: No module named 'simulators'`

**Causa**: O Python não encontra o diretório `src/` no path.

**Solução**: Execute sempre com `uv run` na raiz do repositório:

```bash
uv run --no-sync python scenarios/<cenario>.py
```

### `ModuleNotFoundError: No module named 'mosaik_api_v3'`

**Causa**: Dependências não instaladas.

**Solução**:

```bash
uv sync
```

## Erros do OpenDSS

### `OpenDSSException: Status (...): [OpenDSS 580] Unknown parameter ...`

**Causa**: O motor recusou um comando. A mensagem traz o código e o texto do
OpenDSS — por exemplo `580` (parâmetro inexistente), `302` (comando
inexistente), `303` (valor inválido) ou `180` (algo citado no comando não
existe, como um `linecode`).

**Solução**: O texto diz o que foi recusado. Se o comando veio de um
controlador, confira a unidade e o tipo do valor; se veio do `.dss`, corrija o
arquivo. Com `fail_on_error=False` a mensagem é só impressa e a simulação
segue.

### `OpenDSSException: A solucao nao convergiu em N iteracoes ...`

**Causa**: O fluxo de potência parou no limite de iterações sem convergir — as
tensões desse passo não resolvem o circuito. É comum no primeiro passo depois
do setup, numa manobra de chave ou num salto grande de carga.

**Solução**: Aumente `max_iterations` no `init()` do adaptador. Se preferir não
perder a execução por um passo ruim, use `fail_on_error=False` e registre o
atributo `converged` do modelo `Circuit`. Ilhar geração sem referência de
tensão (abrir a chave que isola uma barra alimentada só por um PV) não tem
solução: aí o fluxo diverge, e mais iterações não ajudam.

### Uma caixa de diálogo do OpenDSS aparece ao iniciar

**Causa**: Há um erro no `.dss` compilado. As caixas de diálogo do OpenDSS
ficam ligadas **só durante a compilação**, de propósito: o motor informa por
texto apenas o erro da última linha do arquivo, e um erro no meio dele só
aparece pela caixa.

**Solução**: Leia a mensagem da caixa, corrija o `.dss` e clique para seguir.
Durante a simulação as caixas ficam desligadas e os erros chegam como
`OpenDSSException`.

### `[OpenTES][ERRO] Falha ao ler a LoadShape '...'`

**Causa**: Uma carga ou gerador declara `daily`/`yearly` com uma curva que não
existe no circuito, ou que não tem pontos.

**Solução**: Corrija o nome da curva no `.dss`. Enquanto isso, o elemento fica
parado no valor nominal durante todo o estudo — é o que o aviso diz.

### Gerador injeta reativa que não foi declarada

**Causa**: Um `Generator` sem `pf` no `.dss` usa o padrão do OpenDSS, `pf=0.88`.
O despacho por `P_set` ou `P_mult` acompanha esse fator.

**Solução**: Declare `pf=1` no `.dss` se o gerador não deve injetar reativa.

### `FileNotFoundError` para arquivos `.dss`

**Causa**: Caminho incorreto ou arquivo não encontrado.

**Solução**: Verifique os caminhos no cenário. Arquivos de dados ficam em `data/`:

```bash
ls data/123Bus/run_ieee123_cosim_pv_5min.dss
```

## Erros Docker

### Container `opendss` sai imediatamente

**Causa**: Entry point incorreto ou módulo não encontrado.

**Solução**: Verifique o `docker-compose.yml`. O serviço deve executar:

```yaml
command: python -m simulators.opendss.api_opendss --remote 0.0.0.0:5771
```

### Cenário não conecta em `localhost:5771`

**Causa**: Containers não estão rodando, portas conflitantes, ou o cenário
aponta para a faixa antiga (5671–5680). No Windows, o WinNAT e o Hyper-V
reservam faixas de portas de forma aleatória — foi por isso que os simuladores
passaram para 5771–5780.

**Solução**:

```bash
# Verificar containers
docker compose ps

# Verificar portas
netstat -an | findstr 5771  # Windows
ss -tlnp | grep 5771        # Linux

# Windows: faixas reservadas pelo sistema
netsh interface ipv4 show excludedportrange protocol=tcp

# Reiniciar
docker compose down
docker compose up -d
```

### `docker build` falha com `"/output": not found`

**Causa**: O `Dockerfile` copia a pasta `output/`, que o git ignora — num clone
novo ela ainda não existe.

**Solução**: Crie a pasta antes de construir a imagem:

```bash
mkdir output
docker build -t opentes-simulador .
```

### Resultado não aparece no host

**Causa**: Volume `./output:/app/output` não montado.

**Solução**: Verifique que o serviço `collector` no `docker-compose.yml` monta o volume.

### Erro de permissão no volume (Linux)

**Solução**:

```bash
sudo chown -R $USER:$USER output/
```

## Erros de simulação

### Valores de tensão zerados

**Causa**: Circuito não foi compilado corretamente ou elementos não existem.

**Solução**: Verifique se o arquivo DSS define todas as barras e elementos esperados.

### SoC da bateria fora dos limites

**Causa**: Parâmetros de eficiência ou potência incompatíveis.

**Solução**: Verifique `pct_eff_charge`, `pct_eff_discharge`, `kw_rated` e `kwh_rated`.

### Tap do regulador não muda

**Causa**: O controle automático dos reguladores do OpenDSS fica **travado** ao
carregar o circuito: os taps só mudam por um controlador externo. Sem um
`RegController` conectado, o tap fica na posição declarada no `.dss` o estudo
inteiro. Com o controlador conectado, a tensão pode estar dentro da faixa morta,
ou o atraso de controle ainda não expirou.

**Solução**: Conecte um `RegController` a cada regulador (ver
[Configurar Regulador](configure-regulator.md)) e verifique `Vref`, `db`,
`Td_ctrl` e a tensão medida.

### O tap pula para 0 no primeiro passo

**Causa**: O `RegController` foi criado com `tap_ini=0` num alimentador que
declara outro tap. Ele envia a própria posição a cada passo, sem ler a do
circuito.

**Solução**: Crie o controlador com `tap_ini=info["tap_ini"]`, o tap que o
adaptador reporta no `extra_info` do `RegControl`.

## Lentidão

### Simulação 123-bus lenta

**Causa**: 288 passos de fluxo de potência em 123 barras.

**Solução**: Normal — cada passo resolve um sistema de equações completo. Para testes rápidos, use `opendss_scenario.py` (13-bus).

## Debug

### Habilitar verbose

Alguns cenários imprimem progresso. Para debug adicional, adicione `print()` no `step()` do adaptador desejado.

### Rodar os testes

```bash
uv run --no-sync python -m pytest tests/ -v
```

A suíte tem dois tipos de teste: os de domínio (bateria, inversor, regulador),
que rodam sem OpenDSS, e os de integração, que compilam circuitos IEEE reais.
Os de integração precisam do motor; no Linux, isso exige a engine compilada (ver
o README). Veja [Testes](../contributing/testing.md).
