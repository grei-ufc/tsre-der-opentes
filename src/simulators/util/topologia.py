"""Exportação avulsa da topologia de um circuito para JSON.

Passa pela fachada :class:`~simulators.opendss.opendss_wrapper.OpenDSS`, e não
por uma instância crua do ``py_dss_interface``: a compilação ganha as mesmas
defesas da co-simulação — o arquivo conferido antes do ``Redirect``, o
diretório de trabalho preservado, os erros do motor detectados — e o JSON sai
pelo mesmo ``grafo_tsdq`` que o adaptador usa.
"""

import datetime as dt

from ..opendss.opendss_wrapper import OpenDSS

# O wrapper pede passo e início da simulação; para só exportar a topologia,
# qualquer valor serve.
_PASSO = dt.timedelta(seconds=900)
_INICIO = dt.datetime(2025, 1, 1)


def exportar_topologia(dss_path, caminho_json_saida):
    """Compila o circuito e grava o grafo dele em JSON.

    Args:
        dss_path: Arquivo ``.dss`` mestre do circuito.
        caminho_json_saida: Onde gravar o JSON.

    Returns:
        O :class:`~simulators.opendss.graph_model.NetworkGraph` exportado.
    """
    print("1. Compilando o circuito via OpenDSS...")
    wrapper = OpenDSS(topofile=dss_path, time_step=_PASSO, start_time=_INICIO)

    print(f"2. Construindo o grafo e salvando em: {caminho_json_saida}")
    grafo = wrapper.grafo_tsdq(caminho_json_saida)

    print(
        f"3. Grafo gerado: {grafo.total_nodes} nós, {grafo.total_edges} arestas "
        f"e {grafo.total_elements} elementos."
    )
    print("Processo concluído com sucesso!")
    return grafo


if __name__ == "__main__":
    # Exemplo de uso
    dss_path = "caminho/para/seu/circuito.dss"
    caminho_json_saida = "topologia_exportada.json"
    exportar_topologia(dss_path, caminho_json_saida)
