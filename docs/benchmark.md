# Benchmark Report

This document captures the latest local benchmark comparison between the Python `asgi-cc` connector and the Java connector, plus a sweep showing how `sliding_window_size` affects the Python connector's performance.

The benchmark harness also supports large-transfer comparison cases for upload and download:

1. `PUT /upload-size`
2. `GET /download-large`

Those cases are controlled with:

- `ASGI_CC_BENCH_LARGE_UPLOAD_SIZE`
- `ASGI_CC_BENCH_LARGE_DOWNLOAD_SIZE`

## Setup

- Project: `asgi-cc`
- Benchmark runner: `./integration/run_benchmark.sh`
- Benchmark date: 2026-04-19
- Environment: macOS (darwin/arm64), OrbStack (Docker Engine 28.5.2)
- Router: Dockerized Java router built from `integration/router/`
- Python app: `integration/example_app/fastapi_service.py`
- Java app: `integration/java_app/src/main/java/RunJavaBenchApp.java`

## Workload

- Requests per case: `300`
- Concurrency: `30`
- POST payload size: `1024` bytes
- Sliding window sweep: `1,2,4,8`

Measured request shapes:

1. `GET /benchmark/ping`
2. `POST /echo`

## Python vs Java

### Case 1: `GET /benchmark/ping`

| Implementation | Direct Mean (ms) | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python (`asgi-cc`) | 49.30 | 56.55 | 7.25 | 1.15x | 0.89x |
| Java connector | 44.23 | 65.32 | 21.10 | 1.48x | 0.70x |

Delta (`Python - Java`):

- Overhead difference: `-13.85 ms`
- Mean ratio difference: `-0.33`

### Case 2: `POST /echo`

| Implementation | Direct Mean (ms) | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python (`asgi-cc`) | 51.23 | 55.26 | 4.03 | 1.08x | 0.95x |
| Java connector | 49.47 | 57.69 | 8.22 | 1.17x | 0.87x |

Delta (`Python - Java`):

- Overhead difference: `-4.18 ms`
- Mean ratio difference: `-0.09`

## Sliding Window Sweep

### Case 1: `GET /benchmark/ping`

| Sliding Window | Proxied RPS | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 570.60 | 49.01 | -2.15 | 0.96x | 1.04x |
| 2 | 564.12 | 49.80 | -1.46 | 0.97x | 1.03x |
| 4 | 550.19 | 51.01 | 1.56 | 1.03x | 0.97x |
| 8 | 553.30 | 50.63 | 4.53 | 1.10x | 0.91x |

Best for this case:

- Highest proxied RPS: window `1`
- Lowest overhead: window `1`

### Case 2: `POST /echo`

| Sliding Window | Proxied RPS | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 504.50 | 56.00 | 2.75 | 1.05x | 0.95x |
| 2 | 511.61 | 55.03 | -1.71 | 0.97x | 1.03x |
| 4 | 520.06 | 54.23 | 1.51 | 1.03x | 0.98x |
| 8 | 514.60 | 54.64 | 2.97 | 1.06x | 0.96x |

Best for this case:

- Highest proxied RPS: window `4`
- Lowest overhead: window `2`

## Conclusions

- The Python `asgi-cc` connector remains lower-overhead than the Java connector in this local setup for both benchmark cases.
- In this environment, larger sliding windows were not universally better. The lightweight `GET /benchmark/ping` case performed best with window `1`, while the `POST /echo` case peaked on throughput at window `4`.
- The sweep suggests `sliding_window_size` should be workload-tuned rather than treated as a simple "bigger is better" setting.

## Reproduce

```bash
cd fastcc
./integration/run_benchmark.sh
```

Optional environment variables:

- `ASGI_CC_APP_PORT`
- `ASGI_CC_JAVA_APP_PORT`
- `ASGI_CC_BENCH_REQUESTS`
- `ASGI_CC_BENCH_CONCURRENCY`
- `ASGI_CC_BENCH_PAYLOAD_SIZE`
- `ASGI_CC_BENCH_SLIDING_WINDOWS`
