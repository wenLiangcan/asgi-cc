# Python Connector Feasibility and Architecture

This document evaluates whether a Python connector can be implemented for FastAPI without converting Cranker traffic back into ordinary loopback HTTP requests.

Short answer:

- Yes, the goal is feasible.
- The correct abstraction is an ASGI adapter around the application.
- No, FastAPI itself will not "accept Cranker packets directly" as a route-level protocol. The adapter must terminate Cranker and translate it into ASGI events.

## Recommendation

Implement the Python connector as an ASGI-side bridge with three layers:

1. `CrankerClient`
   - Manages router registration, reconnect, ping/pong, and the multiplexed WebSocket.
2. `CrankerSession`
   - Owns one connected `cranker_3.0` WebSocket and all per-request stream state.
3. `ASGI bridge`
   - Converts each Cranker request stream into one ASGI `http` scope plus `receive` and `send` callables, then dispatches into the wrapped FastAPI app.

This avoids the Java connector's extra outbound HTTP hop to `target_uri.resolve(dest)`.

## Why Middleware Is Only Partially the Right Term

Pure Starlette/FastAPI middleware wraps inbound ASGI requests that already came from an ASGI server such as Uvicorn.

Cranker traffic does not arrive as a normal ASGI `http` request. It arrives over an outbound client WebSocket initiated by the service toward the router.

So the Python shape should be:

- an ASGI adapter component that has access to the FastAPI app object
- optionally exposed as a helper that feels middleware-like to users
- but technically driven by connector-managed background tasks, not by Uvicorn's inbound request pipeline

A practical API could still look like this:

```python
app = FastAPI()
connector = CrankerConnector(app, config)
```

or:

```python
app.add_middleware(CrankerBridgeMiddleware, connector_config=config)
```

But internally, the component still needs its own router-facing WebSocket client and lifespan hooks.

## Feasibility Analysis

### What Is Easy

- Parsing and serializing `cranker_3.0` frames.
- Multiplexing many request streams over one WebSocket.
- Mapping Cranker request/response bodies to ASGI streaming events.
- Preserving streaming responses such as SSE.
- Avoiding loopback HTTP entirely.

### What Is Hard but Doable

- Correct per-stream flow control using `WINDOW_UPDATE`.
- Handling disconnect races and `RST_STREAM`.
- Running app dispatch safely from background connector tasks instead of from a server-owned request loop.
- Preserving ASGI semantics for client disconnects, `more_body`, and response start/body ordering.

### What Is Not Realistic

- Making FastAPI route handlers speak Cranker packet format natively.
- Reusing standard HTTP middleware exactly as if the request came from Uvicorn unless the connector builds a valid ASGI scope and event stream.

## Key Design Decision

Do not translate Cranker to local HTTP.

Instead:

- Cranker HEADER -> ASGI `scope`
- Cranker DATA -> ASGI `http.request` events
- ASGI `http.response.start` -> Cranker HEADER
- ASGI `http.response.body` -> Cranker DATA
- disconnect or cancellation -> `RST_STREAM` and/or ASGI `http.disconnect`

This is the narrowest correct impedance match for FastAPI.

## ASGI Mapping

### Request Scope

For each new request stream, build an ASGI HTTP scope:

- `type`: `"http"`
- `asgi.version`: `"3.0"`
- `http_version`: parsed from the Cranker request line if present, else `"1.1"`
- `method`: parsed request method
- `scheme`: inferred from forwarded headers if present, otherwise configurable default
- `path`: decoded path portion of `dest`
- `raw_path`: raw bytes path portion
- `query_string`: raw bytes query string
- `headers`: list of lower-case `(name, value)` byte pairs
- `client`: inferred from forwarding headers if available, else `None`
- `server`: derived from host header if available

The adapter should preserve incoming headers except hop-by-hop headers that are meaningless at the ASGI boundary.

### Receive Side

ASGI `receive()` should produce:

- `{"type": "http.request", "body": <bytes>, "more_body": True}` for body chunks
- final `{"type": "http.request", "body": b"", "more_body": False}`
- `{"type": "http.disconnect"}` if the router resets the stream or the connector loses the session before completion

### Send Side

ASGI `send()` should accept:

- `http.response.start`
  - serialize to one or more Cranker HEADER frames
- `http.response.body`
  - serialize body bytes to DATA
  - if `more_body` is false, send final DATA with end-of-stream

Guardrails:

- Ignore or reject duplicate `http.response.start`
- Treat body before start as protocol error
- If the app raises before sending a response, emit `RST_STREAM`

## Flow Control Design

The Java connector already proves that application-layer flow control is required.

The Python design should mirror it.

### Router -> App Request Body

- Maintain a per-stream queue of Cranker DATA payload chunks.
- `receive()` consumes from that queue.
- After each consumed chunk, send `WINDOW_UPDATE(request_id, consumed_bytes)`.

This makes Cranker consumption align with ASGI demand.

### App -> Router Response Body

- Track bytes sent but not yet acknowledged for each stream.
- Stop reading additional ASGI response body chunks once outstanding bytes exceed a high watermark.
- Resume when `WINDOW_UPDATE` reduces outstanding bytes below a low watermark.

Suggested initial thresholds:

- high watermark: `65536`
- low watermark: `16384`

These match the Java connector.

## Concurrency Model

Recommended runtime stack:

- Python 3.11+
- AnyIO or pure `asyncio`
- `websockets` or another client WebSocket library that exposes ping/pong and binary messages cleanly

Per WebSocket session:

- one task reading frames from router
- one task serializing writes to router
- many per-request tasks running the ASGI app

Per request stream:

- request state object
- inbound body queue
- outbound flow-control waiter
- completion future

Never write to the WebSocket concurrently from multiple tasks without a single writer queue.

## Registration and Lifespan

The connector should integrate with FastAPI lifespan:

- on startup:
  - resolve router URIs
  - connect registration sockets
  - start heartbeat and reconnect tasks
- on shutdown:
  - deregister
  - stop accepting new streams
  - wait for active streams to drain up to timeout
  - cancel remaining work

This is conceptually similar to the Java `CrankerConnector.start()` and `stop()`.

## Compatibility Notes

### FastAPI Middleware Compatibility

Once the adapter constructs a normal ASGI scope and dispatches into the app, most FastAPI and Starlette middleware should work unchanged because they sit above the connector boundary.

### Streaming Compatibility

SSE and chunked-style streaming should work because ASGI already models incremental response bodies.

### HTTP/2 Specifics

Cranker header text is still HTTP/1.1-like. That is fine at the ASGI boundary.

Do not expose HTTP/2 pseudo-headers inside ASGI.

### WebSocket Endpoints in FastAPI

This design only covers proxied HTTP requests over Cranker v3 as shown by the Java connector.

FastAPI WebSocket routes are a separate ASGI protocol and are not addressed by the current Java connector code reviewed here.

## Risks

### Router Expectations Beyond Connector Code

The biggest unknown is router-side tolerance and exact semantics not made explicit in the Java connector, especially:

- malformed frame handling
- exact header parsing requirements
- request ID lifecycle guarantees
- behavior around missing reason phrases

Mitigation:

- validate against a real Cranker router early with integration tests

### ASGI Error Mapping

Different ASGI apps and middleware produce failures at different stages:

- before response start
- during streaming response
- after client disconnect

Each case needs deterministic Cranker behavior, usually `RST_STREAM`.

### Memory Pressure

If flow control is wrong, one fast producer can buffer large request or response bodies in memory.

The implementation should enforce:

- bounded queues
- backpressure-aware waiting
- prompt stream cleanup on reset or disconnect

## Proposed Implementation Phases

1. Frame codec
   - parse and serialize `HEADER`, `DATA`, `RST_STREAM`, `WINDOW_UPDATE`
2. Single-session connector
   - one router, one WebSocket, startup/shutdown, ping/pong
3. Single-request ASGI dispatch
   - GET without body
4. Streaming request bodies
5. Streaming responses and SSE
6. Per-stream flow control
7. Sliding window and multi-router registration
8. Graceful deregistration and reconnect policy
9. Interop tests against the existing Java router

## Conclusion

The goal is doable, but the target should be phrased precisely:

- feasible: a Python Cranker connector that makes an existing FastAPI app available transparently through the router without loopback HTTP
- not feasible in the literal sense: making FastAPI handlers consume raw Cranker packets directly

The right architecture is an ASGI bridge that terminates Cranker v3 and presents standard ASGI HTTP semantics to the wrapped app.
