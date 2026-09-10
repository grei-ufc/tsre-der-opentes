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
import contextlib
import json
import logging
import ssl
import threading
from http import HTTPStatus
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = 0.25

# [OpenTES] Tabela propria em vez de `mimetypes.guess_type`. No Windows aquele
# modulo consulta o registro do sistema, que sobrepoe a tabela interna do
# Python: a mesma resposta saia como `text/javascript` numa maquina e
# `application/javascript` noutra, e nesta ultima o `charset` era descartado.
# Servimos tres extensoes; declara-las aqui torna o cabecalho identico em
# qualquer maquina, que e o que o MIME checking estrito do navegador exige.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


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
        # [OpenTES] O buffer é escrito pela thread do mosaik e drenado pela do
        # servidor; `_reset_data_buf` lê e substitui, o que sem trava perderia
        # uma amostra escrita entre as duas operações.
        self._data_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._reset_data_buf()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self):
        """Sobe o servidor num laço de eventos próprio, numa thread de fundo.

        [OpenTES] O servidor não pode viver no laço do mosaik. O encerramento do
        mosaik é ``run_until_complete(shutdown())`` seguido de ``loop.close()``,
        e o ``shutdown()`` apenas chama o ``finalize()`` de cada simulador, sem
        ceder o controle ao laço depois disso. Um cancelamento pedido dali nunca
        chega a ser processado: as tarefas do servidor eram destruídas ainda
        pendentes, despejando ``Task was destroyed but it is pending!`` no fim de
        toda simulação — e, pior que o ruído, os soquetes ficavam sem fechar.

        Com laço próprio o encerramento é síncrono e determinístico: :meth:`close`
        espera de fato o servidor terminar.
        """
        self._loop = asyncio.new_event_loop()
        self._started = threading.Event()
        self._start_error: BaseException | None = None

        self._thread = threading.Thread(
            target=self._serve_forever, name="webvis-server", daemon=True
        )
        self._thread.start()
        self._started.wait()

        if self._start_error is not None:
            raise self._start_error

    def _serve_forever(self):
        """Corpo da thread: abre o servidor e mantém o laço vivo."""
        asyncio.set_event_loop(self._loop)
        try:
            try:
                self._loop.run_until_complete(self._open())
            except BaseException as exc:
                # Amplo de propósito: a falha é repassada intacta a quem chamou
                # start(), na outra thread. Engolir aqui deixaria o simulador
                # achando que a visualização subiu.
                self._start_error = exc
                return
            finally:
                self._started.set()

            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _open(self):
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

    @property
    def port(self) -> int | None:
        """Porta em que o servidor de fato abriu (útil quando se pede a 0)."""
        server = getattr(self, "server", None)
        if server is None:
            return None
        return server.sockets[0].getsockname()[1]

    def close(self, timeout: float = 5.0):
        """Encerra a difusão, fecha o servidor e espera a thread terminar.

        Bloqueante de propósito: quem chama é o ``finalize()`` do simulador, que
        o mosaik invoca de forma síncrona e sem dar mais nenhuma volta no laço
        antes de fechá-lo. Só esperando aqui o encerramento acontece de verdade.
        """
        loop, thread = self._loop, self._thread
        if loop is None or thread is None or not thread.is_alive():
            return

        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), loop).result(timeout)
        except (TimeoutError, asyncio.CancelledError, RuntimeError) as exc:
            # Não vale derrubar uma simulação que já terminou por causa da
            # faxina do servidor; o aviso diz o que ficou para trás.
            logger.warning("webvis: encerramento nao concluido (%s)", exc)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout)

    async def _shutdown(self):
        """Cancela a difusão e fecha o servidor, esperando os dois de fato."""
        # Primeiro os navegadores em espera. Cada conexão aberta tem um handler
        # parado em `await evt_new_data`, e esse Future não é uma operação de
        # websocket: fechar a conexão não o desperta. Sem liberá-lo aqui, o
        # handler nunca retorna e o `wait_closed()` abaixo espera para sempre —
        # era o que ainda sobrava pendente com uma aba aberta.
        self._release_waiters()

        task = getattr(self, "_broadcast_task", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        server = getattr(self, "server", None)
        if server is not None:
            server.close()
            # `close()` no websockets só agenda o fechamento; sem este await as
            # conexões abertas e o soquete de escuta ficam pendentes.
            await server.wait_closed()

    def _release_waiters(self):
        """Acorda os handlers parados à espera do próximo lote de dados."""
        waiters, self.wait_for_update = self.wait_for_update, []
        for evt in waiters:
            if not evt.done():
                evt.cancel()

    def mark_topology_ready(self):
        """Libera os navegadores em espera, a partir da thread do mosaik.

        ``asyncio.Event`` não é seguro entre threads: quem sinaliza é o passo da
        simulação, e o evento pertence ao laço do servidor.
        """
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.topology_ready.set)

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
            content_type = CONTENT_TYPES.get(file_path.suffix.lower())
            if content_type:
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

        except asyncio.CancelledError:
            # [OpenTES] Fim da simulação: `_release_waiters` cancela a espera
            # para que este handler termine. Sair em silêncio é o que permite ao
            # `wait_closed()` concluir.
            logger.debug("websocket encerrado pelo fim da simulacao")
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
        with self._data_lock:
            self.data_buf["time"] = time
            self.data_buf["progress"] = progress
            self.data_buf["node_data"].append(node_data)

    def _reset_data_buf(self):
        with self._data_lock:
            data = self.data_buf
            self.data_buf = {
                "time": None,
                "progress": None,
                "node_data": [],
            }
        return data
