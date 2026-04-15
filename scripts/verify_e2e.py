from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time

import httpx


ROOT = os.path.dirname(os.path.dirname(__file__))


async def wait_for_health(url: str, verify: bool) -> None:
    deadline = time.time() + 60
    async with httpx.AsyncClient(verify=verify, timeout=2) as client:
        while time.time() < deadline:
            try:
                response = await client.get(url)
                if response.status_code < 500:
                    return
            except Exception:
                pass
            await asyncio.sleep(1)
    raise RuntimeError(f"timed out waiting for {url}")


async def wait_for_registration(url: str) -> None:
    deadline = time.time() + 60
    async with httpx.AsyncClient(verify=False, timeout=2) as client:
        while time.time() < deadline:
            try:
                response = await client.get(url)
                response.raise_for_status()
                services = response.json().get("services", {})
                if services:
                    for service in services.values():
                        connectors = service.get("connectors", [])
                        if connectors:
                            return
            except Exception:
                pass
            await asyncio.sleep(1)
    raise RuntimeError(f"timed out waiting for connector registration at {url}")


async def main() -> int:
    env = os.environ.copy()
    env.setdefault("CRANKER_ROUTER_URL", "wss://localhost:12001")
    env.setdefault("CRANKER_VERIFY_SSL", "false")

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "examples.fastapi_service:app",
            "--host",
            "127.0.0.1",
            "--port",
            "18080",
        ],
        cwd=ROOT,
        env=env,
    )

    try:
        await wait_for_health("http://127.0.0.1:18080/health", verify=True)
        await wait_for_health("https://localhost:12001/health", verify=False)
        await wait_for_registration("https://localhost:12001/health/connectors")

        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            hello = await client.get("https://localhost:12000/hello")
            hello.raise_for_status()
            assert hello.json() == {"message": "hello through cranker"}

            echo = await client.post("https://localhost:12000/echo", content=b"payload")
            echo.raise_for_status()
            assert echo.json()["body_text"] == "payload"

            headers = await client.get(
                "https://localhost:12000/headers",
                headers={"x-fast-cc-test": "yes"},
            )
            headers.raise_for_status()
            assert headers.json()["headers"]["x-fast-cc-test"] == "yes"

        print("fast-cc end-to-end verification passed")
        return 0
    finally:
        if server.poll() is None:
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
