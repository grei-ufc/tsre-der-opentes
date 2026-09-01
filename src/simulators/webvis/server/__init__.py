"""Servidor HTTP + WebSocket que entrega a visualização ao navegador.

Fork do pacote ``mosaik_webvis_server`` do mosaik-web 0.5.0 (LGPL-2.1); veja
``../LICENSE.txt`` e ``../README.md``. As mudanças em relação ao original são
comentadas com ``[OpenTES]``.

Os arquivos estáticos saem de ``html/``; ``/websocket`` é a única rota que
chega de fato ao WebSocket. O simulador empurra dados novos com
:meth:`Server.set_new_data` e uma tarefa de fundo os difunde em lotes, para que
a taxa de quadros do navegador não fique atrelada ao passo da simulação.
"""

import asyncio
import json
import logging
import mimetypes
import ssl
from http import HTTPStatus
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = 0.25


class Server:
    def __init__(
        self,
        server_addr: tuple[str, int],
        ssl_filepaths: tuple[str, str | None] | None,
    ):
        self.basedir = Path(__file__).parent / "html"
        """Base directory for static files."""

        self.server_addr = server_addr
        if ssl_filepaths:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl_context.load_cert_chain(*ssl_filepaths)

            mosaik_js = self.basedir / "media/mosaik.js"
            mosaik_js_ssl = self.basedir / "media/mosaik_ssl.js"

            if not mosaik_js_ssl.is_file():
                mosaik_js_str = mosaik_js.read_text()
                mosaik_js_ssl.write_text(mosaik_js_str.replace("ws://", "wss://"))
        else:
            self.ssl_context = None

        self.topology = None
        self.data_buf = {}
        self.wait_for_update: list[asyncio.Future[str]] = []
        self._reset_data_buf()

    async def start(self):
        self.topology_ready = asyncio.Event()

        # [OpenTES] Guardar a referência da tarefa: sem isso o coletor de lixo
        # pode recolher a task ainda em execução (o asyncio só mantém uma
        # referência fraca), matando a difusão de dados no meio da simulação.
        self._broadcast_task = asyncio.create_task(self._broadcast_update())
        try:
            self.server = await serve(
                self._handle_ws,
                *self.server_addr,
                ssl=self.ssl_context,
                process_request=self._intercept_http,
            )
        except OSError as exc:
            # [OpenTES] Sem isto, uma porta ocupada — o caso comum de esquecer
            # outra simulação aberta — sai como um traceback do `websockets`
            # que não diz o que fazer.
            host, port = self.server_addr
            self._broadcast_task.cancel()
            raise OSError(
                f"[OpenTES] Nao foi possivel abrir {host}:{port} para a visualizacao web: "
                f"{exc}. Verifique se outra simulacao ainda esta rodando nessa porta "
                f"ou inicie o WebVis com outra: world.start('WebVis', ..., port=8001)."
            ) from exc

    def close(self):
        """Encerra a difusão e fecha o servidor.

        Síncrono de propósito: quem chama é o ``finalize()`` do simulador, que o
        mosaik invoca fora de qualquer corrotina. Rodando in-process o servidor
        vive no mesmo laço de eventos do mosaik, então deixá-lo aberto no fim da
        simulação sobra como tarefa pendente quando o laço é fechado.
        """
        task = getattr(self, "_broadcast_task", None)
        if task is not None:
            task.cancel()

        server = getattr(self, "server", None)
        if server is not None:
            server.close()

    async def _broadcast_update(self):
        while True:
            await asyncio.sleep(UPDATE_INTERVAL)
            new_data = self._reset_data_buf()
            if new_data["progress"] is None:
                continue

            msg = json.dumps(["update_data", new_data])
            for evt in self.wait_for_update:
                evt.set_result(msg)
            self.wait_for_update = []

    async def _intercept_http(
        self, connection: ServerConnection, request: Request
    ) -> Response | None:
        """Process incoming connections before websockets are set up for
        them.

        Unless the GET path is /websocket, intercept the request to
        serve files from :attr:`basedir`, instead.
        """
        uri = request.path
        if uri == "/websocket":
            return None  # continue along the websocket path in _handle_ws

        if uri.endswith("/"):
            uri += "index.html"

        if self.ssl_context and uri == "/media/mosaik.js":
            uri = "/media/mosaik_ssl.js"

        try:
            file_path = self.basedir / Path(uri).relative_to("/")
            # [OpenTES] Impede que um caminho como '/../../segredo' escape do
            # diretório de estáticos; o servidor original montava o caminho sem
            # validar.
            file_path = file_path.resolve()
            file_path.relative_to(self.basedir.resolve())

            content = file_path.read_text(encoding="utf-8")
            response = connection.respond(HTTPStatus.OK, content)
            content_type = mimetypes.guess_type(uri)[0]
            if content_type:
                if content_type.startswith("text/"):
                    content_type = f"{content_type}; charset=utf-8"
                # [OpenTES] `Headers` do websockets é um multidict: atribuir
                # acrescenta em vez de substituir. Sem apagar antes, a resposta
                # saía com dois `Content-Type` — o `text/plain` que `respond()`
                # põe e o correto — e o navegador, diante do conflito, recusava
                # a folha de estilo (strict MIME checking). O desenho perdia
                # todos os estilos sem um único erro visível: as arestas, que
                # são `<line>` sem `stroke` padrão, simplesmente sumiam.
                del response.headers["Content-Type"]
                response.headers["Content-Type"] = content_type
            return response
        except (FileNotFoundError, ValueError):
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found")

    async def _handle_ws(self, ws: ServerConnection):
        """Process for websocket connections."""
        try:
            msg = await ws.recv()
            assert msg == "get_topology"
            await self.topology_ready.wait()
            await ws.send(json.dumps(["setup_topology", self.topology]))

            while True:
                evt_new_data: asyncio.Future[str] = asyncio.Future()
                self.wait_for_update.append(evt_new_data)
                msg = await evt_new_data
                await ws.send(msg)

        except ConnectionClosed:
            # [OpenTES] Fechar ou recarregar a aba é o caso normal, não um erro.
            # Sem tratá-lo, o `websockets` despejava um traceback no terminal da
            # simulação a cada vez que o usuário recarregava a página.
            logger.debug("websocket fechado pelo cliente")
        except ConnectionError:
            logger.warning('websocket ConnectionError in "Server.websock()"')
        except OSError as e:
            logger.warning(f'websocket OSError in "Server.websocket()": {e}')

    def set_new_data(self, time, progress, node_data):
        self.data_buf["time"] = time
        self.data_buf["progress"] = progress
        self.data_buf["node_data"].append(node_data)

    def _reset_data_buf(self):
        data = self.data_buf
        self.data_buf = {
            "time": None,
            "progress": None,
            "node_data": [],
        }
        return data
