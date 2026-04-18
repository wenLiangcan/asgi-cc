# fastcc

Python work area for a Cranker connector targeting ASGI/FastAPI services.

Package manager: `uv`

This directory currently contains:

- `docs/cranker-v3-protocol.md`: protocol notes extracted from the Java connector
- `docs/architecture.md`: feasibility analysis and Python design proposal
- `docs/benchmark.md`: local direct-vs-proxied benchmark results
- `src/fastcc/`: the connector package
- `integration/`: example app, Maven-based router setup, and e2e runner

Status:

- Only Cranker protocol `cranker_3.0` is in scope.
- The current code is a scaffold, not a finished connector.
- The intended design is an ASGI adapter around an existing FastAPI app, not a loopback HTTP proxy.

## Workflow

Use `uv` for environment and command execution:

```bash
cd fastcc
uv sync
uv run python -m compileall src/fastcc
```

Run the full integration test with one command:

```bash
cd fastcc
./integration/run_e2e.sh
```

Run a simple local benchmark comparing direct FastAPI calls vs Cranker-proxied calls:

```bash
cd fastcc
./integration/run_benchmark.sh
```

The benchmark also runs a Java app using the official Java connector and compares connector-added latency between the Python and Java implementations.

## Runtime Attach/Detach

`CrankerConnector` supports attaching to and detaching from an ASGI app at runtime. These operations automatically manage the connector's connection to the router.

```python
connector = CrankerConnector(config=config)

# Attach an app: automatically calls await connector.startup() 
# and connects to the router if not already started.
await connector.attach(fastapi_app)

# Detach the app: automatically calls await connector.shutdown()
# and disconnects from the router.
await connector.detach()
```

If you start the connector without an app (by calling `await connector.startup()` manually), it will return a `503 Service Unavailable` response to any incoming requests until an app is attached.
