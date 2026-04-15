# fast-cc

Python work area for a Cranker connector targeting ASGI/FastAPI services.

Package manager: `uv`

This directory currently contains:

- `docs/cranker-v3-protocol.md`: protocol notes extracted from the Java connector
- `docs/architecture.md`: feasibility analysis and Python design proposal
- `fast_cc/`: initial Python package scaffold for the future implementation

Status:

- Only Cranker protocol `cranker_3.0` is in scope.
- The current code is a scaffold, not a finished connector.
- The intended design is an ASGI adapter around an existing FastAPI app, not a loopback HTTP proxy.

## Workflow

Use `uv` for environment and command execution:

```bash
cd fast-cc
uv sync
uv run python -m compileall fast_cc
```
