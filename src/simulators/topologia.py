import json
from dataclasses import asdict
from .topology_builder import build_graph
import py_dss_interface

def exportar_topologia(dss_path, caminho_json_saida):
    print("1. Compilando o circuito via OpenDSS...")

    dss = py_dss_interface.DSS()
    dss.text("Clear")
    dss.text(f"compile [{dss_path}]")
    
    print("2. Construindo o grafo e classificando os barramentos...")
    grafo = build_graph(dss)
    
    print(f"3. Grafo gerado: {grafo.total_nodes} nós e {grafo.total_edges} arestas.")
    
    # 4. Convertendo o NetworkGraph para um dicionário serializável em JSON
    # Como as chaves de graph.nodes e graph.edges são strings e os valores são dataclasses,
    # usamos uma list comprehension junto com asdict() para extrair os dados puros.
    grafo_dict = {
        "nodes": [asdict(node) for node in grafo.nodes.values()],
        "edges": [asdict(edge) for edge in grafo.edges.values()]
    }
    
    print(f"4. Salvando dados no arquivo: {caminho_json_saida}")
    with open(caminho_json_saida, 'w', encoding='utf-8') as f:
        json.dump(grafo_dict, f, indent=4, ensure_ascii=False)
        
    print("Processo concluído com sucesso!")

# Exemplo de uso:
# exportar_topologia("meu_circuito_ieee.dss", "topologia_exportada.json")

if __name__ == "__main__":
    # Exemplo de uso
    dss_path = "caminho/para/seu/circuito.dss"
    caminho_json_saida = "topologia_exportada.json"
    exportar_topologia(dss_path, caminho_json_saida)