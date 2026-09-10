"""Tests for the static file serving of the web visualization.

The browser gets its whole appearance from these responses, and it fails
*silently* when they are wrong: a stylesheet rejected over its MIME type takes
down the drawing without a single error, because an SVG ``<line>`` with no
``stroke`` is simply not painted. These tests are the guard for that.
"""

import asyncio
import sys

import pytest
from websockets.sync.client import connect

sys.path.insert(0, "src")

from simulators.webvis.server import Server


async def fetch(port, path):
    """Minimal HTTP/1.1 GET, so the tests need no HTTP client dependency."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()

    raw = await reader.read()
    writer.close()

    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").splitlines()
    status = int(lines[0].split()[1])
    headers = []
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers.append((name.strip().lower(), value.strip()))
    return status, headers, body


def serve_and_get(paths):
    """Sobe o servidor numa porta livre, busca *paths* e encerra.

    O servidor tem laço próprio numa thread, então o cliente pode usar um laço
    qualquer — aqui, um descartável só para as requisições.
    """
    server = Server(("127.0.0.1", 0), None)
    server.start()
    try:
        return asyncio.run(_get_all(server.port, paths))
    finally:
        server.close()


async def _get_all(port, paths):
    return [await fetch(port, path) for path in paths]


@pytest.fixture(scope="module")
def responses():
    paths = ["/", "/media/main.css", "/media/mosaik.js", "/media/nao-existe.css"]
    return dict(zip(paths, serve_and_get(paths), strict=True))


class TestContentType:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/", "text/html"),
            ("/media/main.css", "text/css"),
            ("/media/mosaik.js", "text/javascript"),
        ],
    )
    def test_declared_type_is_the_right_one(self, responses, path, expected):
        _, headers, _ = responses[path]
        types = [value for name, value in headers if name == "content-type"]
        assert types == [f"{expected}; charset=utf-8"]

    def test_content_type_is_not_duplicated(self, responses):
        """`Headers` do websockets é um multidict: atribuir acrescenta.

        Sem apagar o cabeçalho antes, cada resposta saía com o ``text/plain``
        posto por ``respond()`` *e* o tipo correto. Diante do conflito o
        navegador recusa a folha de estilo, e o desenho perde todos os estilos
        sem nenhum erro visível.
        """
        for path, (_, headers, _) in responses.items():
            types = [value for name, value in headers if name == "content-type"]
            assert len(types) == 1, f"{path} respondeu com {types}"


class TestStaticFiles:
    def test_index_is_served_at_the_root(self, responses):
        status, _, body = responses["/"]
        assert status == 200
        assert b'<svg id="canvas">' in body

    def test_media_is_served(self, responses):
        status, _, body = responses["/media/main.css"]
        assert status == 200
        assert b".link" in body

    def test_missing_file_is_a_404(self, responses):
        status, _, _ = responses["/media/nao-existe.css"]
        assert status == 404

    def test_paths_cannot_escape_the_html_directory(self):
        """O caminho era montado sem validar `..`."""
        ((status, _, _),) = serve_and_get(["/../../../pyproject.toml"])
        assert status == 404


class TestShutdown:
    """O encerramento tem de terminar de verdade, não só ser pedido.

    O mosaik chama ``finalize()`` de forma síncrona e fecha o próprio laço logo
    depois, sem dar mais nenhuma volta nele: um cancelamento pedido ali nunca
    seria processado. Daí o servidor ter laço próprio — e daí estes testes, que
    são a única forma de perceber a regressão sem ler o ruído do terminal.
    """

    def test_close_stops_the_thread(self):
        server = Server(("127.0.0.1", 0), None)
        server.start()
        assert server._thread.is_alive()

        server.close()

        assert not server._thread.is_alive()
        assert server._loop.is_closed()

    def test_close_leaves_no_pending_task(self):
        server = Server(("127.0.0.1", 0), None)
        server.start()
        loop = server._loop

        server.close()

        assert [t for t in asyncio.all_tasks(loop) if not t.done()] == []

    def test_close_with_a_connected_client(self):
        """O caso que faltava: um handler parado esperando o próximo lote.

        Esse ``await`` não é uma operação de websocket, então fechar a conexão
        não o desperta — o handler ficava vivo, o ``wait_closed()`` nunca
        concluía e as tarefas eram destruídas pendentes.
        """
        server = Server(("127.0.0.1", 0), None)
        server.start()
        server.topology = {"nodes": [], "links": []}
        server.mark_topology_ready()

        with connect(f"ws://127.0.0.1:{server.port}/websocket") as ws:
            ws.send("get_topology")
            ws.recv(timeout=5)  # setup_topology: o handler entra na espera

            server.close()

        assert not server._thread.is_alive()
        assert [t for t in asyncio.all_tasks(server._loop) if not t.done()] == []

    def test_close_is_idempotent(self):
        server = Server(("127.0.0.1", 0), None)
        server.start()

        server.close()
        server.close()  # não pode levantar

    def test_close_without_start_is_harmless(self):
        Server(("127.0.0.1", 0), None).close()

    def test_port_in_use_is_reported_clearly(self):
        """A porta ocupada é o erro comum de esquecer outra simulação aberta."""
        first = Server(("127.0.0.1", 0), None)
        first.start()
        try:
            second = Server(("127.0.0.1", first.port), None)
            with pytest.raises(OSError, match="visualizacao web"):
                second.start()
        finally:
            first.close()
