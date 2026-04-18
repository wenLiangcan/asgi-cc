from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from asgi_cc import CrankerConnector, CrankerConnectorConfig
from integration.common import start_router_container, stop_router_container, wait_for_connection_count


CONNECTORS_URL = "https://localhost:12001/health/connectors"
PROXY_BASE = "https://localhost:12000"


async def assert_proxy_works(expected_message: str) -> None:
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        response = await client.get(f"{PROXY_BASE}/hello")
        response.raise_for_status()
        assert response.json() == {"message": expected_message}


async def main() -> int:
    await start_router_container()

    current_router_urls = ["wss://127.0.0.1:12001"]

    def resolver(_: list[str]) -> list[str]:
        return list(current_router_urls)

    app = FastAPI()

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"message": "hello dns refresh"}

    connector = CrankerConnector(
        app,
        CrankerConnectorConfig(
            router_urls=["wss://router.example.org"],
            route="*",
            component_name="dns-refresh-test",
            verify_ssl=False,
            sliding_window_size=1,
            router_lookup_by_dns=True,
            router_update_interval_seconds=1,
            router_resolver=resolver,
        ),
    )

    try:
        print("1. Starting with one resolved router address...")
        await connector.startup()
        initial_count = await wait_for_connection_count(CONNECTORS_URL, 1)
        await assert_proxy_works("hello dns refresh")
        print(f"   connection count: {initial_count}")

        print("2. Expanding to two resolved router addresses...")
        current_router_urls[:] = [
            "wss://127.0.0.1:12001",
            "wss://[::1]:12001",
        ]
        expanded_count = await wait_for_connection_count(CONNECTORS_URL, 2)
        await assert_proxy_works("hello dns refresh")
        print(f"   connection count: {expanded_count}")

        print("3. Shrinking back to one resolved router address...")
        current_router_urls[:] = ["wss://127.0.0.1:12001"]
        final_count = await wait_for_connection_count(CONNECTORS_URL, 1)
        await assert_proxy_works("hello dns refresh")
        print(f"   connection count: {final_count}")

        print("4. DNS refresh verification passed")
        return 0
    finally:
        await connector.shutdown()
        stop_router_container()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
