# Benchmark Report

This document captures the latest local benchmark comparison between the Python `asgi-cc` connector and the Java connector, plus a sweep showing how `sliding_window_size` affects the Python connector's performance.

The benchmark harness also supports large-transfer comparison cases for upload and download:

1. `PUT /upload-size`
2. `GET /download-large`

Those cases are controlled with:

- `ASGI_CC_BENCH_LARGE_UPLOAD_SIZE`
- `ASGI_CC_BENCH_LARGE_DOWNLOAD_SIZE`

## GitHub Actions Large Transfer Results

This section captures the large-transfer benchmark run from GitHub Actions rather than a local machine, so the measurements come from the same CI environment used for branch verification.

Setup:

- Benchmark date: 2026-04-21
- Workflow run: `24727299880`
- Runner: `ubuntu-latest`
- Requests per case: `6`
- Concurrency: `2`
- Large upload size: `5242880` bytes
- Large download size: `5242880` bytes
- Sliding window sweep: `1,2,4,8`

Measured request shapes:

1. `PUT /upload-size`
2. `GET /download-large`

### Case 1: `PUT /upload-size`

| Implementation | Direct Mean (ms) | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python (`asgi-cc`) | 24.94 | 853.77 | 828.83 | 34.23x | 0.03x |
| Java connector | 57.08 | 973.86 | 916.77 | 17.06x | 0.06x |

Delta (`Python - Java`):

- Overhead difference: `-87.95 ms`
- Mean ratio difference: `17.17`

Python sliding window sweep:

| Sliding Window | Proxied RPS | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.81 | 523.69 | 498.15 | 20.50x | 0.05x |
| 2 | 4.01 | 497.23 | 470.66 | 18.71x | 0.05x |
| 4 | 4.02 | 474.06 | 449.20 | 19.08x | 0.05x |
| 8 | 5.77 | 345.55 | 317.43 | 12.29x | 0.08x |

Best for this case:

- Highest proxied RPS: window `8`
- Lowest overhead: window `8`

### Case 2: `GET /download-large`

| Implementation | Direct Mean (ms) | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python (`asgi-cc`) | 23.80 | 400.73 | 376.93 | 16.84x | 0.06x |
| Java connector | 50.56 | 753.73 | 703.17 | 14.91x | 0.07x |

Delta (`Python - Java`):

- Overhead difference: `-326.24 ms`
- Mean ratio difference: `1.93`

Python sliding window sweep:

| Sliding Window | Proxied RPS | Proxied Mean (ms) | Mean Overhead (ms) | Latency Ratio | RPS Ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 6.17 | 323.45 | 301.61 | 14.81x | 0.07x |
| 2 | 5.91 | 335.19 | 312.50 | 14.77x | 0.07x |
| 4 | 6.30 | 317.27 | 294.21 | 13.76x | 0.07x |
| 8 | 5.16 | 381.48 | 359.13 | 17.07x | 0.06x |

Best for this case:

- Highest proxied RPS: window `4`
- Lowest overhead: window `4`

Large-transfer conclusions:

- Both connectors add substantial latency on `5 MiB` transfers relative to direct calls, so the proxy cost is very visible for body-heavy traffic.
- In this CI run, the Python connector still showed lower absolute mean overhead than the Java connector for both `5 MiB` upload and `5 MiB` download.
- Larger sliding windows materially helped upload throughput for Python, with window `8` clearly best in this workload.
- Download performance peaked earlier, with window `4` outperforming both lower and higher settings, so the optimal value remains workload-specific.

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
cd asgi-cc
./integration/run_benchmark.sh
```

Optional environment variables:

- `ASGI_CC_APP_PORT`
- `ASGI_CC_JAVA_APP_PORT`
- `ASGI_CC_BENCH_REQUESTS`
- `ASGI_CC_BENCH_CONCURRENCY`
- `ASGI_CC_BENCH_PAYLOAD_SIZE`
- `ASGI_CC_BENCH_LARGE_UPLOAD_SIZE`
- `ASGI_CC_BENCH_LARGE_DOWNLOAD_SIZE`
- `ASGI_CC_BENCH_SLIDING_WINDOWS`
