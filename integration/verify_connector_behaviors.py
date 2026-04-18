from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import FastAPI

from asgi_cc import CrankerConnector, CrankerConnectorConfig
from integration.common import start_router_container, stop_router_container, wait_for_registration


async def verify_route_validation() -> None:
    print("1. Verifying route validation...")
    try:
        CrankerConnectorConfig(
            router_urls=["wss://localhost:12001"],
            route="bad route!",
        )
    except ValueError as exc:
        assert "Routes must contain only letters, numbers, underscores or hyphens" in str(exc)
        print("   route validation passed")
        return
    raise AssertionError("invalid route was accepted")


async def verify_retry_backoff() -> None:
    print("2. Verifying retry backoff shape...")
    connector = CrankerConnector(
        config=CrankerConnectorConfig(
            router_urls=["wss://localhost:12001"],
            route="*",
            reconnect_delay_seconds=1.0,
        )
    )
    delays = [connector._retry_delay_seconds(attempt) for attempt in range(1, 8)]
    assert all(left <= right for left, right in zip(delays, delays[1:]))
    assert any(left < right for left, right in zip(delays, delays[1:]))
    assert delays[-1] <= 11.0
    print(f"   retry delays: {', '.join(f'{delay:.3f}' for delay in delays)}")


async def verify_graceful_deregistration() -> None:
    print("3. Verifying graceful deregistration...")
    await start_router_container()

    app = FastAPI()

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"message": "hello"}

    @app.get("/slow")
    async def slow() -> dict[str, bool]:
        await asyncio.sleep(2)
        return {"done": True}

    connector = CrankerConnector(
        app,
        CrankerConnectorConfig(
            router_urls=["wss://localhost:12001"],
            route="*",
            verify_ssl=False,
            component_name="graceful-stop-test",
            deregister_timeout_seconds=5.0,
        ),
    )

    try:
        await connector.startup()
        await wait_for_registration("https://localhost:12001/health/connectors")

        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            in_flight = asyncio.create_task(client.get("https://localhost:12000/slow"))
            await asyncio.sleep(0.25)

            started = time.perf_counter()
            await connector.shutdown()
            shutdown_elapsed = time.perf_counter() - started

            response = await in_flight
            response.raise_for_status()
            assert response.json() == {"done": True}
            assert shutdown_elapsed >= 1.5

            try:
                after = await client.get("https://localhost:12000/hello", timeout=2)
                assert after.status_code == 404
            except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError):
                pass

        print(f"   graceful shutdown waited {shutdown_elapsed:.2f}s for the in-flight request")
    finally:
        await connector.shutdown()
        stop_router_container()


async def main() -> int:
    await verify_route_validation()
    await verify_retry_backoff()
    await verify_graceful_deregistration()
    print("4. Connector behavior verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
