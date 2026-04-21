# asgi-cc

`asgi-cc` is a Python Cranker connector for ASGI applications. It connects an ASGI app to a Cranker router over WebSocket and forwards HTTP traffic through the Cranker v3 protocol without adding a loopback HTTP hop inside the service process.

## Features

- ASGI-native request and response bridging
- Cranker v3 (`cranker_3.0`) protocol support
- FastAPI-compatible integration
- DNS-based router discovery
- Runtime app attach and detach support

## Requirements

- Python `3.11+`

## Installation

```bash
pip install asgi-cc
```

## Basic Usage

Create the connector with the application and let the app lifecycle manage the connector:

```python
import os

from fastapi import FastAPI

from asgi_cc import CrankerConnector, CrankerConnectorConfig

app = FastAPI()


@app.get("/hello")
async def hello() -> dict[str, str]:
    return {"message": "hello through cranker"}


connector = CrankerConnector(
    app,
    CrankerConnectorConfig(
        router_urls=[os.environ.get("CRANKER_ROUTER_URL", "wss://localhost:12001")],
        route="*",
        verify_ssl=False,
        component_name="my-service",
    ),
)
```

Keep using `app` as the ASGI server entrypoint. The connector registers itself on the app startup and shutdown hooks.

## Middleware Usage

```python
import os

from fastapi import FastAPI

from asgi_cc import CrankerConnector, CrankerConnectorConfig

app = FastAPI()

app.add_middleware(
    CrankerConnector,
    config=CrankerConnectorConfig(
        router_urls=[os.environ.get("CRANKER_ROUTER_URL", "wss://localhost:12001")],
        route="*",
        verify_ssl=False,
        component_name="my-service",
    ),
)
```

## Runtime App Management

```python
connector = CrankerConnector(config=config)

await connector.attach(app)
await connector.detach()
```

If the connector is started without an attached app, incoming requests receive `503 Service Unavailable` until an app is attached.

## Router Discovery

```python
config = CrankerConnectorConfig(
    router_urls=["wss://router.example.org"],
    route="*",
    router_lookup_by_dns=True,
    router_update_interval_seconds=60,
)
```

When enabled, `asgi-cc` resolves router hostnames to IP addresses, opens registrations for the currently resolved routers, and periodically reconciles router registrations as DNS changes.

## Project Links

- Source: <https://github.com/wenLiangcan/asgi-cc>
- Issues: <https://github.com/wenLiangcan/asgi-cc/issues>
