# Benchmark Report

This document captures the local benchmark comparison between the Python (`fastcc`) and Java implementations of the Cranker connector.

## Setup

- **Project**: `fastcc`
- **Benchmark Runner**: `./integration/run_benchmark.sh`
- **App Servers**:
  - Python: FastAPI example app in `integration/example_app/fastapi_service.py`
  - Java: Java bench app in `integration/java_app/src/main/java/RunJavaBenchApp.java`
- **Router**: Dockerized Java router built from `integration/router/`
- **Benchmark Date**: 2026-04-16
- **Environment**: macOS (darwin/arm64), OrbStack (Docker Engine 28.5.2)

## Workload

The benchmark used the default settings from `integration/benchmark.py`:

- **Requests per case**: 300
- **Concurrency**: 30
- **POST payload size**: 1024 bytes

Two request shapes were measured:
1. `GET /benchmark/ping` (Lightweight JSON GET)
2. `POST /echo` (JSON POST with 1KB body)

---

## Results: Python vs. Java Comparison

The following tables compare the **overhead** introduced by each connector implementation (Proxied Latency - Direct Latency).

### Case 1: `GET /benchmark/ping`

| Implementation | Direct Mean (ms) | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **Python (fastcc)** | 51.50 | 65.72 | **14.22** | 1.28x | 0.79x |
| **Java Connector** | 44.33 | 72.49 | **28.16** | 1.64x | 0.62x |

**Delta (Python - Java)**:
- **Overhead Difference**: -13.94 ms (Python is ~14ms faster in overhead)
- **Mean Ratio Difference**: -0.36

### Case 2: `POST /echo` (1024-byte body)

| Implementation | Direct Mean (ms) | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **Python (fastcc)** | 51.08 | 62.29 | **11.21** | 1.22x | 0.83x |
| **Java Connector** | 50.47 | 71.30 | **20.84** | 1.41x | 0.72x |

**Delta (Python - Java)**:
- **Overhead Difference**: -9.63 ms (Python is ~10ms faster in overhead)
- **Mean Ratio Difference**: -0.19

---

## Performance Analysis

Based on the benchmark results, the **Python (`fastcc`) implementation currently shows lower proxying overhead** compared to the Java implementation in this local environment.

### Key Observations:
1.  **Lower Latency Overhead**: In both GET and POST cases, the Python connector added significantly less overhead to the base request time (~11-14ms) compared to the Java connector (~21-28ms).
2.  **Better Efficiency Ratio**: The Python implementation maintained a higher percentage of the direct-path throughput (approx. 80-83% of direct RPS) compared to the Java implementation (approx. 62-72% of direct RPS).
3.  **Consistency**: Both implementations handled the 1KB POST payload with similar relative overhead to their GET performance, suggesting stable handling of request/response bodies in the v3 protocol.

### Technical Context:
- The Python implementation (`fastcc`) is built using an asynchronous ASGI-native approach, which likely reduces context switching and overhead when bridging between the router's WebSocket connections and the FastAPI application logic.
- The Java "bench app" uses a simple `HttpServer` and the standard `CrankerConnector`. The higher overhead in the Java results might be attributed to the specific threading model or the overhead of the Java HTTP client used in the benchmark setup.

## Conclusion

The Python `fastcc` connector is a highly performant alternative for ASGI/FastAPI services. It demonstrates that a Python-based implementation of the Cranker v3 protocol can match or exceed the performance of the reference Java implementation for common web workloads, particularly in terms of minimizing the latency tax introduced by the proxy layer.

## Reproduce

```bash
cd fastcc
./integration/run_benchmark.sh
```

Optional environment variables:
- `FASTCC_BENCH_REQUESTS`
- `FASTCC_BENCH_CONCURRENCY`
- `FASTCC_BENCH_PAYLOAD_SIZE`
- `FASTCC_APP_PORT`
