from __future__ import annotations

import os
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from fastcc import CrankerConnector, CrankerConnectorConfig

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="fastcc demo service")

connector = CrankerConnector(
    app,
    CrankerConnectorConfig(
        router_urls=[os.environ.get("CRANKER_ROUTER_URL", "wss://localhost:12001")],
        route=os.environ.get("CRANKER_ROUTE", "*"),
        domain=os.environ.get("CRANKER_DOMAIN", "*"),
        component_name="fastcc-demo",
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
