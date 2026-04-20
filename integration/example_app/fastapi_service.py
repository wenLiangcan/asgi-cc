from __future__ import annotations

import os
import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from asgi_cc import CrankerConnector, CrankerConnectorConfig

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="asgi-cc demo service")

connector = CrankerConnector(
    app,
    CrankerConnectorConfig(
        router_urls=[os.environ.get("CRANKER_ROUTER_URL", "wss://localhost:12001")],
        route=os.environ.get("CRANKER_ROUTE", "*"),
        domain=os.environ.get("CRANKER_DOMAIN", "*"),
        component_name="asgi-cc-demo",
        router_lookup_by_dns=os.environ.get("ASGI_CC_ROUTER_LOOKUP_BY_DNS", "false").lower() == "true",
        router_update_interval_seconds=float(os.environ.get("ASGI_CC_ROUTER_UPDATE_INTERVAL_SECONDS", "60")),
        sliding_window_size=int(os.environ.get("ASGI_CC_SLIDING_WINDOW_SIZE", "2")),
        verify_ssl=os.environ.get("CRANKER_VERIFY_SSL", "false").lower() == "true",
    ),
)


@app.get("/hello")
async def hello() -> dict[str, str]:
    return {"message": "hello through cranker"}


@app.post("/echo")
async def echo(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse(
        {
            "method": request.method,
            "path": request.url.path,
            "body_text": body.decode("utf-8"),
        }
    )


@app.api_route(
    "/methods",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def methods(request: Request) -> Response:
    body = await request.body()
    headers = {"x-method-seen": request.method}
    payload = {
        "method": request.method,
        "path": request.url.path,
        "query": request.url.query,
        "body_size": len(body),
    }
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    return JSONResponse(payload, headers=headers)


@app.put("/upload-size")
async def upload_size(request: Request) -> JSONResponse:
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
    return JSONResponse({"size": size})


@app.get("/download-large")
async def download_large(size: int = 5 * 1024 * 1024) -> StreamingResponse:
    chunk = b"x" * 65536

    async def body():
        remaining = size
        while remaining > 0:
            part = chunk[: min(len(chunk), remaining)]
            remaining -= len(part)
            yield part

    return StreamingResponse(body(), media_type="application/octet-stream")


@app.get("/headers")
async def headers(request: Request) -> JSONResponse:
    return JSONResponse({"headers": dict(request.headers)})


@app.get("/health")
async def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/benchmark/ping")
async def benchmark_ping() -> dict[str, str]:
    return {"ok": "true"}
