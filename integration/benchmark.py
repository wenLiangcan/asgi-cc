from __future__ import annotations

import asyncio
import math
import os
import statistics
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

import httpx

from integration.common import (
    start_example_app,
    start_java_example_app,
    start_router_container,
    stop_example_app,
    stop_java_example_app,
    stop_router_container,
)


DIRECT_BASE = "http://127.0.0.1:{port}"
PROXY_BASE = "https://localhost:12000"
AppHandle = TypeVar("AppHandle")


@dataclass(slots=True)
class BenchmarkCase:
    name: str
    method: str
    path: str
    body: bytes | None = None
    headers: dict[str, str] | None = None
    expected_status: int = 200


@dataclass(slots=True)
class BenchmarkResult:
    label: str
    count: int
    concurrency: int
    elapsed_seconds: float
    latencies_ms: list[float]

    @property
    def rps(self) -> float:
        return self.count / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0


@dataclass(slots=True)
class ConnectorBenchmarkSummary:
    connector_name: str
    direct: BenchmarkResult
    proxied: BenchmarkResult

    @property
    def mean_overhead_ms(self) -> float:
        return statistics.fmean(self.proxied.latencies_ms) - statistics.fmean(self.direct.latencies_ms)

    @property
    def mean_ratio(self) -> float:
        direct_mean = statistics.fmean(self.direct.latencies_ms)
        proxied_mean = statistics.fmean(self.proxied.latencies_ms)
        return proxied_mean / direct_mean if direct_mean else 0.0

    @property
    def rps_ratio(self) -> float:
        return self.proxied.rps / self.direct.rps if self.direct.rps else 0.0


@dataclass(slots=True)
class SlidingWindowBenchmarkSummary:
    sliding_window_size: int
    summary: ConnectorBenchmarkSummary


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((p / 100.0) * len(ordered)) - 1))
    return ordered[index]


async def make_request(client: httpx.AsyncClient, case: BenchmarkCase) -> float:
    started = time.perf_counter()
    response = await client.request(case.method, case.path, content=case.body, headers=case.headers)
    elapsed = (time.perf_counter() - started) * 1000.0
    if response.status_code != case.expected_status:
        raise RuntimeError(f"{case.name} returned {response.status_code}, expected {case.expected_status}")
    return elapsed


async def run_benchmark(
    base_url: str,
    *,
    case: BenchmarkCase,
    requests: int,
    concurrency: int,
    verify: bool,
) -> BenchmarkResult:
    semaphore = asyncio.Semaphore(concurrency)
    latencies_ms: list[float] = []

    async with httpx.AsyncClient(base_url=base_url, verify=verify, timeout=30.0) as client:
        async def worker() -> None:
            async with semaphore:
                latencies_ms.append(await make_request(client, case))

        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(requests)))
        elapsed = time.perf_counter() - started

    return BenchmarkResult(
        label=base_url,
        count=requests,
        concurrency=concurrency,
        elapsed_seconds=elapsed,
        latencies_ms=latencies_ms,
    )


def print_result(title: str, result: BenchmarkResult) -> None:
    print(title)
    print(f"  requests: {result.count}")
    print(f"  concurrency: {result.concurrency}")
    print(f"  elapsed_s: {result.elapsed_seconds:.3f}")
    print(f"  rps: {result.rps:.2f}")
    print(f"  mean_ms: {statistics.fmean(result.latencies_ms):.2f}")
    print(f"  median_ms: {statistics.median(result.latencies_ms):.2f}")
    print(f"  p95_ms: {percentile(result.latencies_ms, 95):.2f}")
    print(f"  p99_ms: {percentile(result.latencies_ms, 99):.2f}")


def print_summary(summary: ConnectorBenchmarkSummary) -> None:
    print(summary.connector_name)
    print(f"  mean_overhead_ms: {summary.mean_overhead_ms:.2f}")
    print(f"  mean_ratio: {summary.mean_ratio:.2f}x")
    print(f"  rps_ratio: {summary.rps_ratio:.2f}x")


def print_connector_delta(python_summary: ConnectorBenchmarkSummary, java_summary: ConnectorBenchmarkSummary) -> None:
    overhead_gap = python_summary.mean_overhead_ms - java_summary.mean_overhead_ms
    ratio_gap = python_summary.mean_ratio - java_summary.mean_ratio
    print("connector delta")
    print(f"  python_minus_java_overhead_ms: {overhead_gap:.2f}")
    print(f"  python_minus_java_mean_ratio: {ratio_gap:.2f}")


def print_sliding_window_summary(summary: SlidingWindowBenchmarkSummary) -> None:
    print(f"sliding-window-size={summary.sliding_window_size}")
    print(f"  proxied_rps: {summary.summary.proxied.rps:.2f}")
    print(f"  proxied_mean_ms: {statistics.fmean(summary.summary.proxied.latencies_ms):.2f}")
    print(f"  mean_overhead_ms: {summary.summary.mean_overhead_ms:.2f}")
    print(f"  mean_ratio: {summary.summary.mean_ratio:.2f}x")
    print(f"  rps_ratio: {summary.summary.rps_ratio:.2f}x")


async def benchmark_connector(
    *,
    connector_name: str,
    app_port: int,
    case: BenchmarkCase,
    requests: int,
    concurrency: int,
    start_app: Callable[[int], Awaitable[AppHandle]],
    stop_app: Callable[[AppHandle], None],
) -> ConnectorBenchmarkSummary:
    app_process = await start_app(app_port)
    try:
        direct = await run_benchmark(
            DIRECT_BASE.format(port=app_port),
            case=case,
            requests=requests,
            concurrency=concurrency,
            verify=True,
        )
        proxied = await run_benchmark(
            PROXY_BASE,
            case=case,
            requests=requests,
            concurrency=concurrency,
            verify=False,
        )
        return ConnectorBenchmarkSummary(
            connector_name=connector_name,
            direct=direct,
            proxied=proxied,
        )
    finally:
        stop_app(app_process)


async def benchmark_python_sliding_window(
    *,
    app_port: int,
    case: BenchmarkCase,
    requests: int,
    concurrency: int,
    sliding_window_size: int,
) -> SlidingWindowBenchmarkSummary:
    summary = await benchmark_connector(
        connector_name=f"python-asgi-cc-window-{sliding_window_size}",
        app_port=app_port,
        case=case,
        requests=requests,
        concurrency=concurrency,
        start_app=lambda port: start_example_app(
            port,
            extra_env={"ASGI_CC_SLIDING_WINDOW_SIZE": str(sliding_window_size)},
        ),
        stop_app=stop_example_app,
    )
    return SlidingWindowBenchmarkSummary(
        sliding_window_size=sliding_window_size,
        summary=summary,
    )


def parse_sliding_window_sizes() -> list[int]:
    raw_value = os.environ.get("ASGI_CC_BENCH_SLIDING_WINDOWS", "1,2,4,8")
    values: list[int] = []
    for item in raw_value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        value = int(stripped)
        if value <= 0:
            raise ValueError("ASGI_CC_BENCH_SLIDING_WINDOWS must contain positive integers")
        values.append(value)
    if not values:
        raise ValueError("ASGI_CC_BENCH_SLIDING_WINDOWS must not be empty")
    return values


async def main() -> int:
    python_app_port = int(os.environ.get("ASGI_CC_APP_PORT", "18081"))
    java_app_port = int(os.environ.get("ASGI_CC_JAVA_APP_PORT", "18082"))
    requests = int(os.environ.get("ASGI_CC_BENCH_REQUESTS", "300"))
    concurrency = int(os.environ.get("ASGI_CC_BENCH_CONCURRENCY", "30"))
    payload_size = int(os.environ.get("ASGI_CC_BENCH_PAYLOAD_SIZE", "1024"))
    sliding_window_sizes = parse_sliding_window_sizes()
    payload = b"x" * payload_size

    cases = [
        BenchmarkCase(name="json-get", method="GET", path="/benchmark/ping"),
        BenchmarkCase(
            name="echo-post",
            method="POST",
            path="/echo",
            body=payload,
            headers={"content-type": "application/octet-stream"},
        ),
    ]

    await start_router_container()
    try:
        for case in cases:
            print(f"\ncase: {case.name}")
            python_summary = await benchmark_connector(
                connector_name="python-asgi-cc",
                app_port=python_app_port,
                case=case,
                requests=requests,
                concurrency=concurrency,
                start_app=start_example_app,
                stop_app=stop_example_app,
            )
            java_summary = await benchmark_connector(
                connector_name="java-connector",
                app_port=java_app_port,
                case=case,
                requests=requests,
                concurrency=concurrency,
                start_app=start_java_example_app,
                stop_app=stop_java_example_app,
            )

            print("python-asgi-cc direct")
            print_result("direct", python_summary.direct)
            print("python-asgi-cc proxied")
            print_result("proxied", python_summary.proxied)
            print_summary(python_summary)

            print("java-connector direct")
            print_result("direct", java_summary.direct)
            print("java-connector proxied")
            print_result("proxied", java_summary.proxied)
            print_summary(java_summary)

            print_connector_delta(python_summary, java_summary)

            print("python-asgi-cc sliding-window sweep")
            sliding_window_summaries: list[SlidingWindowBenchmarkSummary] = []
            for sliding_window_size in sliding_window_sizes:
                summary = await benchmark_python_sliding_window(
                    app_port=python_app_port,
                    case=case,
                    requests=requests,
                    concurrency=concurrency,
                    sliding_window_size=sliding_window_size,
                )
                print_sliding_window_summary(summary)
                sliding_window_summaries.append(summary)

            best_rps = max(sliding_window_summaries, key=lambda item: item.summary.proxied.rps)
            best_latency = min(sliding_window_summaries, key=lambda item: item.summary.mean_overhead_ms)
            print("sliding-window best")
            print(f"  best_rps_window: {best_rps.sliding_window_size}")
            print(f"  best_rps: {best_rps.summary.proxied.rps:.2f}")
            print(f"  lowest_overhead_window: {best_latency.sliding_window_size}")
            print(f"  lowest_overhead_ms: {best_latency.summary.mean_overhead_ms:.2f}")
        return 0
    finally:
        stop_router_container()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
