from __future__ import annotations

import asyncio
import os

import httpx

from integration.common import (
    fetch_connection_count,
    start_example_app,
    start_router_container,
    stop_example_app,
    stop_router_container,
)


CONNECTORS_URL = "https://localhost:12001/health/connectors"
PROXY_BASE = "https://localhost:12000"


async def assert_proxy_works(expected_message: str) -> None:
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        response = await client.get(f"{PROXY_BASE}/hello")
        response.raise_for_status()
        assert response.json() == {"message": expected_message}


async def main() -> int:
    app_port = int(os.environ.get("ASGI_CC_APP_PORT", "18081"))

    await start_router_container()
    baseline_server = None
    dns_server = None
    try:
        print("1. Starting connector without DNS router lookup...")
        baseline_server = await start_example_app(
            app_port,
            extra_env={
                "ASGI_CC_ROUTER_LOOKUP_BY_DNS": "false",
                "ASGI_CC_SLIDING_WINDOW_SIZE": "1",
            },
        )
        baseline_connections = await fetch_connection_count(CONNECTORS_URL)
        await assert_proxy_works("hello through cranker")
        print(f"   baseline connection count: {baseline_connections}")
        stop_example_app(baseline_server)
        baseline_server = None

        print("2. Starting connector with DNS router lookup enabled...")
        dns_server = await start_example_app(
            app_port,
            extra_env={
                "ASGI_CC_ROUTER_LOOKUP_BY_DNS": "true",
                "ASGI_CC_ROUTER_UPDATE_INTERVAL_SECONDS": "2",
                "ASGI_CC_SLIDING_WINDOW_SIZE": "1",
            },
        )
        dns_connections = await fetch_connection_count(CONNECTORS_URL)
        await assert_proxy_works("hello through cranker")
        print(f"   dns connection count: {dns_connections}")

        assert baseline_connections >= 1
        assert dns_connections >= 2
        assert dns_connections > baseline_connections
        print("3. DNS router lookup verification passed")
        return 0
    finally:
        if baseline_server is not None:
            stop_example_app(baseline_server)
        if dns_server is not None:
            stop_example_app(dns_server)
        stop_router_container()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
