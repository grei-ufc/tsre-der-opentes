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

### `OpenDSSException: Error executing command`

**Causa**: Comando DSS inválido ou arquivo `.dss` com erro.

**Solução**:

1. Verifique se o arquivo `.dss` existe no caminho especificado
2. Verifique se o circuito compila corretamente no OpenDSS standalone
3. Verifique se os LoadShapes estão definidos

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
command: python -m simulators.opendss.api_opendss --remote 0.0.0.0:5671
```

### Cenário não conecta em `localhost:5671`

**Causa**: Containers não estão rodando ou portas conflitantes.

**Solução**:

```bash
# Verificar containers
docker compose ps

# Verificar portas
netstat -an | findstr 5671  # Windows
ss -tlnp | grep 5671        # Linux

# Reiniciar
docker compose down
docker compose up -d
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

**Causa**: Tensão dentro da faixa morta ou atraso de controle não expirou.

**Solução**: Verifique `Vref`, `db`, `Td_ctrl` e a tensão medida.

## Lentidão

### Simulação 123-bus lenta

**Causa**: 288 passos de fluxo de potência em 123 barras.

**Solução**: Normal — cada passo resolve um sistema de equações completo. Para testes rápidos, use `opendss_scenario.py` (13-bus).

## Debug

### Habilitar verbose

Alguns cenários imprimem progresso. Para debug adicional, adicione `print()` no `step()` do adaptador desejado.

### Rodar testes unitários

```bash
uv run --no-sync python -m pytest tests/ -v
```

Testes isolam os modelos de domínio (bateria, inversor, regulador) sem OpenDSS.
