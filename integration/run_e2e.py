from __future__ import annotations

import asyncio
import os

import httpx

from integration.common import start_example_app, start_router_container, stop_example_app, stop_router_container

async def main() -> int:
    app_port = int(os.environ.get("ASGI_CC_APP_PORT", "18081"))

    await start_router_container()
    server = await start_example_app(app_port)

    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            hello = await client.get("https://localhost:12000/hello")
            hello.raise_for_status()
            assert hello.json() == {"message": "hello through cranker"}

            echo = await client.post("https://localhost:12000/echo", content=b"payload")
            echo.raise_for_status()
            assert echo.json()["body_text"] == "payload"

            headers = await client.get(
                "https://localhost:12000/headers",
                headers={"x-asgi-cc-test": "yes"},
            )
            headers.raise_for_status()
            assert headers.json()["headers"]["x-asgi-cc-test"] == "yes"

        print("asgi-cc end-to-end verification passed")
        return 0
    finally:
        stop_example_app(server)
        stop_router_container()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
