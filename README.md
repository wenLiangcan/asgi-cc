# asgi-cc

`asgi-cc` is a Python Cranker connector for ASGI applications. It connects an ASGI app to a Cranker router over WebSocket and forwards HTTP traffic through the Cranker v3 protocol without introducing a loopback HTTP hop inside the service process.

The project is designed to let existing ASGI applications participate in a Cranker deployment with minimal integration work. The current implementation targets the latest protocol generation only: `cranker_3.0`.

## Features

- ASGI-native request and response bridging
- Cranker v3 (`cranker_3.0`) protocol support
- FastAPI-compatible integration model
- Runtime app attach and detach support

## Requirements

- Python `3.11+`

## Usage Patterns

`asgi-cc` supports two practical integration patterns for ASGI applications.

### Wrapper Pattern

Create the connector with the application and let the app's startup and shutdown hooks manage the connector lifecycle:

```python
import os

from fastapi import FastAPI

from asgi_cc import CrankerConnector, CrankerConnectorConfig

app = FastAPI()


@app.get("/hello")
async def hello() -> dict[str, str]:
    return {"message": "hello from wrapper"}


connector = CrankerConnector(
    app,
    CrankerConnectorConfig(
        router_urls=[os.environ.get("CRANKER_ROUTER_URL", "wss://localhost:12001")],
        route="*",
        verify_ssl=False,
        component_name="wrapper-pattern",
    ),
)
```

Keep using `app` as the ASGI server entrypoint. The connector registers itself on the app lifecycle hooks.

### Middleware Pattern

Attach the connector as middleware and keep the application as the ASGI entrypoint:

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
        component_name="middleware-pattern",
    ),
)


@app.get("/hello")
async def hello() -> dict[str, str]:
    return {"message": "hello from middleware"}
```

Reference examples live under `integration/patterns/`.

## Runtime App Management

`CrankerConnector` can be started without an attached ASGI app and can attach or detach an app at runtime.

```python
connector = CrankerConnector(config=config)

await connector.attach(app)
await connector.detach()
```

If the connector is started without an attached app, incoming requests receive `503 Service Unavailable` until an app is attached.

## Router Discovery

By default, `asgi-cc` connects to the router URLs listed in `router_urls`.

To follow DNS A/AAAA records and reconcile router registrations as DNS changes, enable DNS-based router discovery:

```python
config = CrankerConnectorConfig(
    router_urls=["wss://router.example.org"],
    route="*",
    router_lookup_by_dns=True,
    router_update_interval_seconds=60,
)
```

When enabled, `asgi-cc` resolves the router hostnames to IP addresses, opens registrations for the currently resolved routers, and periodically adds or removes router registrations as DNS changes.

## Integration Test

Run the local end-to-end verification against the Dockerized Cranker router:

```bash
cd fastcc
./integration/run_e2e.sh
```

## Benchmark

Run the local benchmark suite:

```bash
cd fastcc
./integration/run_benchmark.sh
```

The benchmark compares:

- direct requests to the ASGI app
- requests proxied through Cranker with `asgi-cc`
- requests proxied through Cranker with the Java connector reference setup
- Python connector runs with multiple `sliding_window_size` values to show how connection parallelism affects performance
- both small request/response cases and large transfer cases for upload and download

Environment variables:

- `ASGI_CC_APP_PORT`
- `ASGI_CC_JAVA_APP_PORT`
- `ASGI_CC_BENCH_REQUESTS`
- `ASGI_CC_BENCH_CONCURRENCY`
- `ASGI_CC_BENCH_PAYLOAD_SIZE`
- `ASGI_CC_BENCH_LARGE_UPLOAD_SIZE`
- `ASGI_CC_BENCH_LARGE_DOWNLOAD_SIZE`
- `ASGI_CC_BENCH_SLIDING_WINDOWS`

## Developer Notes

### Project Layout

- `src/asgi_cc/`: connector package
- `docs/cranker-v3-protocol.md`: protocol notes extracted from the Java connector
- `docs/architecture.md`: architecture and feasibility notes
- `docs/benchmark.md`: local benchmark results
- `integration/`: local router setup, example app, verification scripts, and benchmark tooling

### Development Checks

```bash
cd fastcc
uv run python -m compileall src/asgi_cc integration
uv run ty check
```

## Status

- `cranker_3.0` is the only supported protocol version
- the project focuses on ASGI applications rather than an internal loopback HTTP client
- the integration and benchmark tooling are intended for local validation during development
