from __future__ import annotations

import asyncio
import math
import os
import statistics
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

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


async def benchmark_connector(
    *,
    connector_name: str,
    app_port: int,
    case: BenchmarkCase,
    requests: int,
    concurrency: int,
    start_app: Callable[[int], Awaitable[object]],
    stop_app: Callable[[object], None],
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


async def main() -> int:
    python_app_port = int(os.environ.get("FASTCC_APP_PORT", "18081"))
    java_app_port = int(os.environ.get("FASTCC_JAVA_APP_PORT", "18082"))
    requests = int(os.environ.get("FASTCC_BENCH_REQUESTS", "300"))
    concurrency = int(os.environ.get("FASTCC_BENCH_CONCURRENCY", "30"))
    payload_size = int(os.environ.get("FASTCC_BENCH_PAYLOAD_SIZE", "1024"))
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
                connector_name="python-fastcc",
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

            print("python-fastcc direct")
            print_result("direct", python_summary.direct)
            print("python-fastcc proxied")
            print_result("proxied", python_summary.proxied)
            print_summary(python_summary)

            print("java-connector direct")
            print_result("direct", java_summary.direct)
            print("java-connector proxied")
            print_result("proxied", java_summary.proxied)
            print_summary(java_summary)

            print_connector_delta(python_summary, java_summary)
        return 0
    finally:
        stop_router_container()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
