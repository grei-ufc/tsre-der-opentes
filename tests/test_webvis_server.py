"""Tests for the static file serving of the web visualization.

The browser gets its whole appearance from these responses, and it fails
*silently* when they are wrong: a stylesheet rejected over its MIME type takes
down the drawing without a single error, because an SVG ``<line>`` with no
``stroke`` is simply not painted. These tests are the guard for that.
"""

import asyncio
import sys

import pytest

sys.path.insert(0, "src")

from simulators.webvis.server import Server


async def fetch(port, path):
    """Minimal HTTP/1.1 GET, so the tests need no HTTP client dependency."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode()
    )
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
    """Sobe o servidor numa porta livre, busca *paths* e encerra."""

    async def run():
        server = Server(("127.0.0.1", 0), None)
        await server.start()
        port = server.server.sockets[0].getsockname()[1]
        try:
            return [await fetch(port, path) for path in paths]
        finally:
            server.close()

    return asyncio.run(run())


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
        assert b"<svg id=\"canvas\">" in body

    def test_media_is_served(self, responses):
        status, _, body = responses["/media/main.css"]
        assert status == 200
        assert b".link" in body

    def test_missing_file_is_a_404(self, responses):
        status, _, _ = responses["/media/nao-existe.css"]
        assert status == 404

    def test_paths_cannot_escape_the_html_directory(self):
        """O caminho era montado sem validar `..`."""
        (status, _, _), = serve_and_get(["/../../../pyproject.toml"])
        assert status == 404
