from __future__ import annotations

import asyncio
import os

import httpx

from integration.common import start_example_app, start_router_container, stop_example_app, stop_router_container


PROXY_BASE = "https://localhost:12000"
COMMON_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
UPLOAD_SIZE = 5 * 1024 * 1024
DOWNLOAD_SIZE = 2 * 1024 * 1024


async def verify_methods(client: httpx.AsyncClient) -> None:
    for method in COMMON_METHODS:
        request = client.build_request(
            method,
            f"{PROXY_BASE}/methods?via=proxy",
            content=b"payload" if method in {"POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else None,
        )
        response = await client.send(request)
        response.raise_for_status()

        assert response.headers["x-method-seen"] == method
        if method == "HEAD":
            assert response.text == ""
            continue

        payload = response.json()
        assert payload["method"] == method
        assert payload["path"] == "/methods"
        assert payload["query"] == "via=proxy"
        expected_size = 7 if method in {"POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else 0
        assert payload["body_size"] == expected_size


async def verify_large_upload(client: httpx.AsyncClient) -> None:
    response = await client.put(f"{PROXY_BASE}/upload-size", content=b"u" * UPLOAD_SIZE, timeout=60)
    response.raise_for_status()
    assert response.json() == {"size": UPLOAD_SIZE}


async def verify_large_download(client: httpx.AsyncClient) -> None:
    total = 0
    async with client.stream("GET", f"{PROXY_BASE}/download-large?size={DOWNLOAD_SIZE}", timeout=60) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            total += len(chunk)
    assert total == DOWNLOAD_SIZE


async def main() -> int:
    app_port = int(os.environ.get("ASGI_CC_APP_PORT", "18081"))

    await start_router_container()
    server = await start_example_app(app_port)
    try:
        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            await verify_methods(client)
            await verify_large_upload(client)
            await verify_large_download(client)

        print("asgi-cc HTTP method and large body verification passed")
        return 0
    finally:
        stop_example_app(server)
        stop_router_container()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
