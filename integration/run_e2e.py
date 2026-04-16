from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

import httpx


ROOT = pathlib.Path(__file__).resolve().parent.parent
INTEGRATION_DIR = ROOT / "integration"
DOCKERFILE = INTEGRATION_DIR / "router" / "Dockerfile"
ROUTER_IMAGE = "fastcc-router"
ROUTER_CONTAINER = "fastcc-router-test"


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
                text = response.text
                if "connectors" in text and "connectionCount" in text:
                    return
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


def run_command(command: list[str], *, cwd: pathlib.Path | None = None) -> None:
    subprocess.run(command, cwd=cwd or ROOT, check=True)


def ensure_docker_available() -> None:
    try:
        run_command(["docker", "version"])
        return
    except Exception:
        pass

    orbctl = shutil.which("orbctl")
    if orbctl is not None:
        run_command([orbctl, "start"])
        for _ in range(30):
            try:
                run_command(["docker", "version"])
                return
            except Exception:
                time.sleep(1)

    raise RuntimeError("docker is not available")

async def main() -> int:
    env = os.environ.copy()
    env.setdefault("CRANKER_ROUTER_URL", "wss://localhost:12001")
    env.setdefault("CRANKER_VERIFY_SSL", "false")
    app_port = int(env.get("FASTCC_APP_PORT", "18081"))

    ensure_docker_available()
    subprocess.run(
        ["docker", "rm", "-f", ROUTER_CONTAINER],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run_command(["docker", "build", "-t", ROUTER_IMAGE, "-f", str(DOCKERFILE), "."], cwd=ROOT)
    run_command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            ROUTER_CONTAINER,
            "-p",
            "12000:12000",
            "-p",
            "12001:12001",
            ROUTER_IMAGE,
        ],
        cwd=ROOT,
    )
    await wait_for_health("https://localhost:12001/health", verify=False)

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "integration.example_app.fastapi_service:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(app_port),
        ],
        cwd=ROOT,
        env=env,
    )

    try:
        await wait_for_health(f"http://127.0.0.1:{app_port}/health", verify=True)
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
                headers={"x-fastcc-test": "yes"},
            )
            headers.raise_for_status()
            assert headers.json()["headers"]["x-fastcc-test"] == "yes"

        print("fastcc end-to-end verification passed")
        return 0
    finally:
        if server.poll() is None:
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        subprocess.run(
            ["docker", "rm", "-f", ROUTER_CONTAINER],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
