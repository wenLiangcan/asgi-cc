from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
import uuid
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any, Awaitable, Callable
from urllib.parse import unquote, urlparse

from .config import CrankerConnectorConfig
from .protocol import (
    CRANKER_V3,
    Frame,
    MessageType,
    build_response_head,
    decode_frame,
    default_reason_phrase,
    encode_data_frame,
    encode_header_frame,
    encode_rst_stream_frame,
    encode_window_update_frame,
    parse_request_head,
    split_header_text,
)

try:
    from websockets.asyncio.client import ClientConnection, connect
except ImportError:  # pragma: no cover
    from websockets.client import WebSocketClientProtocol as ClientConnection  # type: ignore
    from websockets.client import connect  # type: ignore


logger = logging.getLogger("asgi_cc.connector")

ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]

_REQUEST_END = object()
_REQUEST_DISCONNECT = object()


@dataclass(slots=True)
class _QueuedWrite:
    payload: bytes
    future: asyncio.Future[None]


@dataclass(slots=True)
class _StreamState:
    request_id: int
    session: "CrankerSession"
    header_chunks: list[str] = field(default_factory=list)
    request_queue: asyncio.Queue[bytes | object] = field(default_factory=asyncio.Queue)
    app_task: asyncio.Task[None] | None = None
    response_started: bool = False
    response_complete: bool = False
    disconnected: bool = False
    pending_write_bytes: int = 0
    window_condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def receive(self) -> dict[str, Any]:
        item = await self.request_queue.get()
        if item is _REQUEST_DISCONNECT:
            self.disconnected = True
            return {"type": "http.disconnect"}
        if item is _REQUEST_END:
            return {"type": "http.request", "body": b"", "more_body": False}
        assert isinstance(item, bytes)
        await self.session.send_frame(encode_window_update_frame(self.request_id, len(item)))
        return {"type": "http.request", "body": item, "more_body": True}

    async def send(self, message: dict[str, Any]) -> None:
        if self.disconnected:
            return
        message_type = message["type"]
        if message_type == "http.response.start":
            if self.response_started:
                raise RuntimeError("response already started")
            self.response_started = True
            status = int(message["status"])
            headers = list(message.get("headers", []))
            reason = default_reason_phrase(status)
            head = build_response_head(status, reason, headers)
            chunks = split_header_text(head)
            for index, chunk in enumerate(chunks):
                payload = encode_header_frame(
                    self.request_id,
                    chunk,
                    header_end=index == len(chunks) - 1,
                    stream_end=False,
                )
                await self._send_with_flow_control(payload, len(chunk.encode("utf-8")))
            return

        if message_type == "http.response.body":
            if not self.response_started:
                raise RuntimeError("response body sent before response start")
            body = bytes(message.get("body", b""))
            more_body = bool(message.get("more_body", False))
            payload = encode_data_frame(self.request_id, body, stream_end=not more_body)
            await self._send_with_flow_control(payload, len(body))
            if not more_body:
                self.response_complete = True
                self.session.streams.pop(self.request_id, None)
            return

        raise RuntimeError(f"unsupported ASGI message type {message_type!r}")

    async def on_window_update(self, ack_bytes: int) -> None:
        async with self.window_condition:
            self.pending_write_bytes = max(0, self.pending_write_bytes - ack_bytes)
            if self.pending_write_bytes < self.session.config.flow_control_low_watermark:
                self.window_condition.notify_all()

    async def close_from_router(self) -> None:
        self.disconnected = True
        await self.request_queue.put(_REQUEST_DISCONNECT)
        if self.app_task is not None and not self.app_task.done():
            self.app_task.cancel()

    async def _send_with_flow_control(self, frame_payload: bytes, logical_bytes: int) -> None:
        await self.session.send_frame(frame_payload)
        if logical_bytes:
            async with self.window_condition:
                self.pending_write_bytes += logical_bytes
                while (
                    self.pending_write_bytes > self.session.config.flow_control_high_watermark
                    and not self.disconnected
                ):
                    await self.window_condition.wait()


class CrankerSession:
    def __init__(self, connector: "CrankerConnector", websocket: ClientConnection) -> None:
        self.connector = connector
        self.config = connector.config
        self.websocket = websocket
        self.streams: dict[int, _StreamState] = {}
        self._write_queue: asyncio.Queue[_QueuedWrite | None] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        self._writer_task = asyncio.create_task(self._writer_loop(), name="asgi-cc-writer")
        try:
            async for raw_message in self.websocket:
                if not isinstance(raw_message, bytes):
                    continue
                await self._handle_frame(decode_frame(raw_message))
        finally:
            logger.info("session closing")
            await self._close_streams()
            await self._write_queue.put(None)
            if self._writer_task is not None:
                await self._writer_task

    async def send_frame(self, payload: bytes) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._write_queue.put(_QueuedWrite(payload=payload, future=future))
        await future

    async def _writer_loop(self) -> None:
        while True:
            item = await self._write_queue.get()
            if item is None:
                return
            try:
                await self.websocket.send(item.payload)
            except Exception as exc:  # pragma: no cover
                if not item.future.done():
                    item.future.set_exception(exc)
                raise
            else:
                if not item.future.done():
                    item.future.set_result(None)

    async def _handle_frame(self, frame: Frame) -> None:
        if frame.message_type == MessageType.HEADER:
            await self._handle_header(frame)
            await self.send_frame(encode_window_update_frame(frame.request_id, len(frame.payload)))
            return
        if frame.message_type == MessageType.DATA:
            await self._handle_data(frame)
            return
        if frame.message_type == MessageType.WINDOW_UPDATE:
            if len(frame.payload) >= 4 and frame.request_id in self.streams:
                ack_bytes = int.from_bytes(frame.payload[:4], byteorder="big", signed=True)
                await self.streams[frame.request_id].on_window_update(ack_bytes)
            return
        if frame.message_type == MessageType.RST_STREAM:
            state = self.streams.pop(frame.request_id, None)
            if state is not None:
                await state.close_from_router()

    async def _handle_header(self, frame: Frame) -> None:
        state = self.streams.get(frame.request_id)
        if state is None:
            state = _StreamState(request_id=frame.request_id, session=self)
            self.streams[frame.request_id] = state

        state.header_chunks.append(frame.payload.decode("utf-8"))
        if not frame.is_header_end:
            return

        request_head = parse_request_head("".join(state.header_chunks))
        state.app_task = asyncio.create_task(
            self._run_asgi_request(state, request_head),
            name=f"asgi-cc-request-{frame.request_id}",
        )
        if frame.is_stream_end:
            await state.request_queue.put(_REQUEST_END)

    async def _handle_data(self, frame: Frame) -> None:
        state = self.streams.get(frame.request_id)
        if state is None:
            return
        if frame.payload:
            await state.request_queue.put(frame.payload)
        if frame.is_stream_end:
            await state.request_queue.put(_REQUEST_END)

    async def _run_asgi_request(self, state: _StreamState, request_head: Any) -> None:
        await self.connector._request_started()
        try:
            scope = self._build_scope(request_head)
            app = self.connector.app
            if app is None:
                await self._send_503(state.send)
                return

            await app(scope, state.receive, state.send)
            if not state.response_started:
                await state.send(
                    {
                        "type": "http.response.start",
                        "status": 204,
                        "headers": [],
                    }
                )
                await state.send(
                    {
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if state.request_id in self.streams:
                self.streams.pop(state.request_id, None)
                with contextlib.suppress(Exception):
                    await self.send_frame(
                        encode_rst_stream_frame(
                            state.request_id,
                            1011,
                            f"asgi app error: {exc}",
                        )
                    )
        finally:
            await self.connector._request_finished()

    @staticmethod
    async def _send_503(send: ASGISend) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Service Unavailable: No app attached",
                "more_body": False,
            }
        )

    def _build_scope(self, request_head: Any) -> dict[str, Any]:
        headers: list[tuple[bytes, bytes]] = []
        header_map: dict[bytes, bytes] = {}
        for line in request_head.header_lines:
            if not line:
                continue
            pos = line.find(":")
            if pos <= 0:
                continue
            name = line[:pos].strip().lower().encode("latin-1")
            value = line[pos + 1 :].strip().encode("latin-1")
            headers.append((name, value))
            header_map[name] = value

        scheme = self.config.forwarded_scheme
        if scheme is None:
            scheme = header_map.get(b"x-forwarded-proto", b"http").decode("latin-1")

        host = header_map.get(b"host", b"")
        server: tuple[str, int | None] | None = None
        if host:
            host_text = host.decode("latin-1")
            if ":" in host_text:
                server_host, server_port_text = host_text.rsplit(":", 1)
                with contextlib.suppress(ValueError):
                    server = (server_host, int(server_port_text))
            if server is None:
                server = (host_text, 80 if scheme == "http" else 443)

        client: tuple[str, int] | None = None
        forwarded_for = header_map.get(b"x-forwarded-for")
        if forwarded_for:
            client = (forwarded_for.decode("latin-1").split(",")[0].strip(), 0)

        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": request_head.http_version.removeprefix("HTTP/"),
            "method": request_head.method,
            "scheme": scheme,
            "path": unquote(request_head.raw_path.decode("ascii")),
            "raw_path": request_head.raw_path,
            "query_string": request_head.query_string,
            "root_path": "",
            "headers": headers,
            "client": client,
            "server": server,
            "state": {},
        }

    async def _close_streams(self) -> None:
        pending = list(self.streams.values())
        self.streams.clear()
        for state in pending:
            await state.close_from_router()


class CrankerConnector:
    def __init__(
        self,
        app: ASGIApp | None = None,
        config: CrankerConnectorConfig | None = None,
    ) -> None:
        self.app = app
        self.config = config or CrankerConnectorConfig()
        if self.config.connector_instance_id is None:
            self.config.connector_instance_id = str(uuid.uuid4())
        self._router_tasks: dict[tuple[str, int], asyncio.Task[None]] = {}
        self._refresh_task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()
        self._started = False
        self._active_request_count = 0
        self._active_request_condition = asyncio.Condition()

        if app is not None:
            self._register_hooks(app)

    async def _request_started(self) -> None:
        async with self._active_request_condition:
            self._active_request_count += 1

    async def _request_finished(self) -> None:
        async with self._active_request_condition:
            self._active_request_count = max(0, self._active_request_count - 1)
            if self._active_request_count == 0:
                self._active_request_condition.notify_all()

    async def attach(self, app: ASGIApp) -> None:
        """Attach an ASGI app and automatically start the connector if not already started."""
        self.app = app
        self._register_hooks(app)
        if not self._started:
            await self.startup()

    async def detach(self) -> None:
        """Detach the current ASGI app and automatically shut down the connector."""
        if self._started:
            await self.shutdown()
        self.app = None

    def _register_hooks(self, app: ASGIApp) -> None:
        logger.debug("registering hooks for app type: %s", type(app))
        add_event_handler = getattr(app, "add_event_handler", None)
        if callable(add_event_handler):
            logger.debug("found add_event_handler on app")
            add_event_handler("startup", self.startup)
            add_event_handler("shutdown", self.shutdown)
        else:
            router = getattr(app, "router", None)
            on_event = getattr(router, "on_event", None)
            if callable(on_event):
                logger.debug("found on_event on app.router")
                on_event("startup")(self.startup)
                on_event("shutdown")(self.shutdown)
            else:
                logger.debug("no lifecycle hooks found on app")

    async def startup(self) -> None:
        if self._started:
            return
        logger.info("starting connector for routes=%s", self.config.route)
        self._started = True
        self._shutdown = asyncio.Event()
        await self._refresh_router_registrations()
        if self.config.router_lookup_by_dns:
            self._refresh_task = asyncio.create_task(
                self._router_refresh_loop(),
                name="asgi-cc-router-refresh",
            )

    async def shutdown(self) -> None:
        if not self._started:
            return
        logger.info("shutting down connector")
        self._shutdown.set()
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
            self._refresh_task = None
        await self._deregister_all()
        await self._wait_for_active_requests()
        for task in self._router_tasks.values():
            task.cancel()
        results = await asyncio.gather(*self._router_tasks.values(), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                pass
        self._router_tasks.clear()
        self._started = False
        self.app = None  # auto detach on shutdown

    async def _wait_for_active_requests(self) -> None:
        try:
            async with self._active_request_condition:
                await asyncio.wait_for(
                    self._wait_until_no_active_requests(),
                    timeout=self.config.deregister_timeout_seconds,
                )
        except TimeoutError:
            logger.warning(
                "graceful deregistration timed out with %s active request(s)",
                self._active_request_count,
            )

    async def _wait_until_no_active_requests(self) -> None:
        while self._active_request_count > 0:
            await self._active_request_condition.wait()

    async def _router_refresh_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(self.config.router_update_interval_seconds)
                if self._shutdown.is_set():
                    return
                await self._refresh_router_registrations()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("router DNS refresh failed")

    async def _refresh_router_registrations(self) -> None:
        resolved_router_urls = await self._resolve_router_urls()
        desired_keys = {
            (router_url, slot)
            for router_url in resolved_router_urls
            for slot in range(self.config.sliding_window_size)
        }
        existing_keys = set(self._router_tasks)
        removed_router_urls = {router_url for router_url, _ in (existing_keys - desired_keys)}

        for router_url in sorted(removed_router_urls):
            logger.info("removing router %s after router update", router_url)
            await self._deregister_router(router_url)

        for key in sorted(existing_keys - desired_keys):
            router_url, slot = key
            task = self._router_tasks.pop(key)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        for key in sorted(desired_keys - existing_keys):
            router_url, slot = key
            logger.info("adding router %s slot %s after router update", router_url, slot)
            self._router_tasks[key] = asyncio.create_task(
                self._socket_worker(router_url, slot),
                name=f"asgi-cc-router-{slot}",
            )

    async def _resolve_router_urls(self) -> list[str]:
        if self.config.router_resolver is not None:
            resolved = self.config.router_resolver(self.config.router_urls)
            if hasattr(resolved, "__await__"):
                resolved = await resolved
            return list(dict.fromkeys(resolved))

        if not self.config.router_lookup_by_dns:
            return list(dict.fromkeys(self.config.router_urls))

        loop = asyncio.get_running_loop()
        resolved: list[str] = []
        for router_url in self.config.router_urls:
            parsed = urlparse(router_url)
            if parsed.scheme not in {"ws", "wss"}:
                raise ValueError(f"router URL must use ws or wss: {router_url!r}")
            if parsed.hostname is None:
                raise ValueError(f"router URL must include a hostname: {router_url!r}")

            default_port = 443 if parsed.scheme == "wss" else 80
            address_info = await loop.getaddrinfo(
                parsed.hostname,
                parsed.port or default_port,
                type=0,
                proto=0,
            )
            for _, _, _, _, sockaddr in address_info:
                host = sockaddr[0]
                resolved.append(self._replace_host_with_ip(parsed, host))
        return list(dict.fromkeys(resolved))

    def _replace_host_with_ip(self, parsed: Any, host: str) -> str:
        port = parsed.port
        host_text = ip_address(host).compressed
        if ":" in host_text:
            host_text = f"[{host_text}]"
        return parsed._replace(netloc=f"{host_text}:{port}" if port is not None else host_text).geturl()

    async def _socket_worker(self, router_url: str, slot: int) -> None:
        attempts = 0
        while not self._shutdown.is_set():
            try:
                async with connect(
                    self._register_url(router_url),
                    subprotocols=self.config.preferred_protocols,
                    additional_headers=self._registration_headers(),
                    ping_interval=self.config.ping_interval_seconds,
                    ping_timeout=self.config.idle_timeout_seconds,
                    ssl=self._ssl_context_for_url(router_url),
                    open_timeout=5,
                ) as websocket:
                    if websocket.subprotocol != CRANKER_V3:
                        raise RuntimeError(
                            f"expected negotiated subprotocol {CRANKER_V3}, got {websocket.subprotocol!r}"
                        )
                    logger.info("connected to router %s on slot %s", router_url, slot)
                    attempts = 0
                    session = CrankerSession(self, websocket)
                    await session.run()
                    logger.info(
                        "router session ended for %s slot %s with close code=%s reason=%s",
                        router_url,
                        slot,
                        websocket.close_code,
                        websocket.close_reason,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("router worker failed for %s slot %s", router_url, slot)
                attempts += 1
                await asyncio.sleep(self._retry_delay_seconds(attempts))

    def _retry_delay_seconds(self, attempts: int) -> float:
        return min(10.0, self.config.reconnect_delay_seconds * float(2 ** max(0, attempts - 1)))

    async def _deregister_all(self) -> None:
        router_urls = {router_url for router_url, _ in self._router_tasks}
        for router_url in router_urls:
            await self._deregister_router(router_url)

    async def _deregister_router(self, router_url: str) -> None:
        with contextlib.suppress(Exception):
            async with connect(
                self._deregister_url(router_url),
                additional_headers=self._registration_headers(),
                ssl=self._ssl_context_for_url(router_url),
                open_timeout=5,
            ) as websocket:
                await websocket.close()

    def _registration_headers(self) -> list[tuple[str, str]]:
        return [
            ("CrankerProtocol", "1.0"),
            ("Route", self.config.route),
            ("Domain", self.config.domain),
        ]

    def _register_url(self, router_url: str) -> str:
        return (
            f"{router_url.rstrip('/')}/register/"
            f"?connectorInstanceID={self.config.connector_instance_id}"
            f"&componentName={self.config.component_name}"
        )

    def _deregister_url(self, router_url: str) -> str:
        return (
            f"{router_url.rstrip('/')}/deregister/"
            f"?connectorInstanceID={self.config.connector_instance_id}"
            f"&componentName={self.config.component_name}"
        )

    def _ssl_context_for_url(self, router_url: str) -> ssl.SSLContext | bool | None:
        parsed = urlparse(router_url)
        if parsed.scheme != "wss":
            return None
        if self.config.verify_ssl:
            return ssl.create_default_context()
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    async def __call__(self, scope: dict[str, Any], receive: ASGIReceive, send: ASGISend) -> None:
        if scope["type"] == "lifespan":
            async def wrapped_receive() -> dict[str, Any]:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await self.startup()
                elif message["type"] == "lifespan.shutdown":
                    await self.shutdown()
                return message

            if self.app is not None:
                await self.app(scope, wrapped_receive, send)
            else:
                # Fallback if being used as the main ASGI app without an attached app
                while True:
                    message = await wrapped_receive()
                    if message["type"] == "lifespan.startup":
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        await send({"type": "lifespan.shutdown.complete"})
                        return
            return

        if self.app is None:
            if scope["type"] == "http":
                await CrankerSession._send_503(send)
                return
            raise RuntimeError("No app attached to CrankerConnector")

        await self.app(scope, receive, send)
