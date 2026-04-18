from __future__ import annotations

import os
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

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


@app.get("/headers")
async def headers(request: Request) -> JSONResponse:
    return JSONResponse({"headers": dict(request.headers)})


@app.get("/health")
async def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/benchmark/ping")
async def benchmark_ping() -> dict[str, str]:
    return {"ok": "true"}
