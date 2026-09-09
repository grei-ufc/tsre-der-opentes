import json

import py_dss_interface

from ..opendss.graph_model import serialize_graph
from ..opendss.topology_builder import build_graph


def exportar_topologia(dss_path, caminho_json_saida):
    print("1. Compilando o circuito via OpenDSS...")

    dss = py_dss_interface.DSS()
    dss.text("Clear")
    dss.text(f"compile [{dss_path}]")

    print("2. Construindo o grafo e classificando os barramentos...")
    grafo = build_graph(dss)

    print(
        f"3. Grafo gerado: {grafo.total_nodes} nós, {grafo.total_edges} arestas "
        f"e {grafo.total_elements} elementos."
    )

    # 4. Convertendo o NetworkGraph para um dicionário serializável em JSON
    grafo_dict = serialize_graph(grafo)

    print(f"4. Salvando dados no arquivo: {caminho_json_saida}")
    with open(caminho_json_saida, "w", encoding="utf-8") as f:
        json.dump(grafo_dict, f, indent=4, ensure_ascii=False)

    print("Processo concluído com sucesso!")


# Exemplo de uso:
# exportar_topologia("meu_circuito_ieee.dss", "topologia_exportada.json")

if __name__ == "__main__":
    # Exemplo de uso
    dss_path = "caminho/para/seu/circuito.dss"
    caminho_json_saida = "topologia_exportada.json"
    exportar_topologia(dss_path, caminho_json_saida)
