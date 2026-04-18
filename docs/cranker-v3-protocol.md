# Cranker v3 Protocol Notes

This document is derived from the Java connector in `cranker-connector`, primarily:

- `ConnectorSocketV3.java`
- `RouterRegistration.java`
- `CrankerConnector.java`
- `ConnectorSocketAdapter.java`
- `CrankerResponseBuilder.java`

It describes the latest connector-side protocol version used by the Java implementation: `cranker_3.0`.

## Scope

This is a connector-oriented protocol description, not a full router specification. A few router behaviors are inferred from the connector code and tests rather than defined by an explicit standalone spec.

## Transport

- Connector and router communicate over a single WebSocket connection.
- The WebSocket subprotocol is negotiated with `Sec-WebSocket-Protocol`.
- Supported values in the Java connector are `cranker_3.0` and `cranker_1.0`.
- For the Python work, only `cranker_3.0` should be implemented.

## Registration Lifecycle

The connector does not connect to a data path directly. It registers with router registration endpoints first.

### Registration URI

For each configured router base URI, the Java connector derives:

- Register endpoint: `/register/?connectorInstanceID=<id>&componentName=<name>`
- Deregister endpoint: `/deregister/?connectorInstanceID=<id>&componentName=<name>`

These paths are resolved against the supplied router URI.

### Registration Request Headers

Each WebSocket registration request includes:

- `CrankerProtocol: 1.0`
  - Present for backward compatibility.
  - This header is not the same thing as the WebSocket subprotocol.
- `Route: <route>`
- `Domain: <domain>`

The connector also offers preferred subprotocols with:

- first preferred protocol as the primary subprotocol
- remaining values as fallback subprotocols

The default Java order is:

1. `cranker_3.0`
2. `cranker_1.0`

### Sliding Window

The Java connector maintains `slidingWindowSize` idle WebSocket registrations per router.

For `cranker_3.0`, each WebSocket can multiplex multiple requests concurrently. The Java code still maintains a configured number of idle registered sockets per router for availability and balancing.

### Reconnect Behavior

If registration fails, the Java connector retries with exponential backoff:

- delay = `500 + min(10000, 2^attempts)` milliseconds

### Liveness

Once connected, the connector:

- sends WebSocket ping frames every 5 seconds
- closes the socket if no message or ping/pong activity is seen for 20 seconds

## WebSocket Message Model

`cranker_3.0` uses only binary WebSocket messages for tunneled traffic. `onText` is unused.

Each complete Cranker binary message starts with a 6-byte prefix:

1. `message_type`: 1 byte
2. `flags`: 1 byte
3. `request_id`: 4 bytes, signed Java `int`, big-endian

After that comes the message-type-specific payload.

The Java implementation assumes one complete Cranker message per completed WebSocket message. If the underlying WebSocket library delivers continuation fragments, it buffers them until the final fragment before decoding the Cranker frame.

## Message Types

### `0x00` DATA

Payload:

- raw body bytes, optional

Flags:

- bit `0x01`: stream end

Semantics:

- Router -> connector: request body bytes for an existing request stream.
- Connector -> router: response body bytes for an existing request stream.
- A DATA frame with `stream end` set and no payload is used to signal end-of-stream.

### `0x01` HEADER

Payload:

- UTF-8 encoded header text chunk

Flags:

- bit `0x01`: stream end
- bit `0x04`: header end

Semantics:

- HEADER frames carry the request start-line plus request headers, or the response status-line plus response headers.
- Large headers may be split across multiple HEADER frames.
- Only the final HEADER frame in a header block has `header end` set.
- `stream end` indicates there is no body after the header block.

#### Request Header Text Format

The Java connector parses request headers as newline-delimited UTF-8 text:

```text
<METHOD> <DEST> <HTTP-VERSION>\n
<header-name>:<value>\n
<header-name>:<value>\n
...
```

Notes:

- The request line is split on spaces.
- `DEST` is forwarded to the target application path and query.
- The Java v3 parser ignores the trailing HTTP version after parsing the first two tokens.
- Header lines are split on the first `:`.
- HTTP/2 pseudo-headers such as `:method`, `:path`, `:authority` are ignored by the Java connector when forwarding to the target.

#### Response Header Text Format

The Java connector serializes response headers as:

```text
HTTP/1.1 <STATUS> <REASON>\n
<header-name>:<value>\n
<header-name>:<value>\n
...
```

Notes:

- The Java code currently writes `"TODO"` as the reason phrase in v3 response headers.
- Response headers whose names start with `:` are omitted.
- The response header text does not append an extra blank line terminator.
- Response header blocks larger than 16000 characters are chunked across multiple HEADER frames.

### `0x03` RST_STREAM

Payload:

- `error_code`: 4 bytes, big-endian integer
- `message`: optional UTF-8 bytes

Flags:

- unused in the Java connector

Semantics:

- Either side can abort a single multiplexed request stream.
- When the connector receives `RST_STREAM`, it cancels local request/response work for that request ID.
- When the connector emits `RST_STREAM`, it also removes the request context.

Observed Java-side error code use:

- `1011` for internal processing failures, cancellation, or upstream/downstream IO errors

### `0x08` WINDOW_UPDATE

Payload:

- `window_update`: 4 bytes, big-endian integer

Flags:

- unused in the Java connector

Semantics:

- Acknowledges how many body/header bytes were consumed for one request stream.
- Used by the sender to release backpressure and request more data from its local producer.

The Java connector sends `WINDOW_UPDATE`:

- after consuming inbound request DATA bytes
- after consuming inbound HEADER chunk bytes

The value equals the payload bytes consumed, not including the 6-byte Cranker frame prefix.

## Multiplexing

- Each in-flight request on a WebSocket has a distinct `request_id`.
- Frames from multiple request IDs may interleave freely.
- Per-request ordering must be preserved.
- Request context is keyed by `request_id`.

The connector creates local per-request state containing:

- parsed request metadata
- request body subscriber
- response body subscription
- flow-control counters
- buffered partial request headers

## Flow Control

The Java connector implements connector-side flow control per request stream.

### Inbound Request Body

For router -> connector request bodies:

- inbound DATA frames are queued until the local request-body subscriber requests demand
- after the connector hands `N` bytes to the local subscriber, it sends `WINDOW_UPDATE(request_id, N)`

### Outbound Response Body

For connector -> router response bodies:

- the connector tracks bytes sent but not yet acknowledged
- high watermark: `64 KiB`
- low watermark: `16 KiB`
- when unacknowledged bytes exceed the high watermark, the connector stops pulling more body data from the local response stream
- when acknowledgements reduce outstanding bytes below the low watermark, the connector resumes pulling

The exact Java counters are:

- `wssSendingBytes`: sent but not yet acknowledged
- `wssReceivedAckBytes`: bytes acknowledged by peer

This is not TCP-level flow control. It is an application-level per-stream backpressure mechanism layered on top of WebSocket.

## Mapping to Local HTTP Semantics in Java

The Java connector converts Cranker traffic into ordinary outbound HTTP requests against a configured target URI.

### Request Construction

- destination URI: `target_uri.resolve(dest)`
- method: from the request line
- headers: copied except disallowed request headers and pseudo-headers
- request body:
  - no body if `stream end` is set on the HEADER frame
  - streamed from incoming DATA frames otherwise

### Response Construction

- status code: from local upstream response
- reason phrase: static placeholder `"TODO"` in v3
- headers: copied except pseudo-headers
- response body: streamed into DATA frames
- final empty DATA with `stream end` closes the response body

## Shutdown

Graceful shutdown uses a separate WebSocket to `/deregister/` with:

- `CrankerProtocol: 1.0`
- `Route: <route>`
- `Domain: <domain>`

After deregistration:

- idle sockets are marked stopping
- active streams are allowed to finish until timeout
- remaining work is cancelled if timeout is reached

## Important Inferences and Unknowns

These points are inferred from connector code and may need router confirmation before relying on them as normative protocol rules:

- `request_id` allocation strategy is router-defined; the connector only consumes it.
- Router expectations for reason phrase content appear loose because the connector sends `"TODO"` in v3 responses.
- Exact router behavior for malformed header chunking, duplicate `request_id`, and oversized Cranker frames is not defined in the Java connector.
- The Java connector uses Java `String.length()` when chunking response headers at 16000 characters; in a Python implementation, chunk on encoded byte length instead to avoid UTF-8 boundary bugs.
