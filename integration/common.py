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
JAVA_APP_DIR = INTEGRATION_DIR / "java_app"
JAVA_APP_DOCKERFILE = JAVA_APP_DIR / "Dockerfile"
JAVA_APP_IMAGE = "fastcc-java-bench-app"
JAVA_APP_CONTAINER = "fastcc-java-bench-app-test"
DOCKER_NETWORK = "fastcc-bench-net"


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


def ensure_docker_network() -> None:
    inspected = subprocess.run(
        ["docker", "network", "inspect", DOCKER_NETWORK],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspected.returncode == 0:
        return
    run_command(["docker", "network", "create", DOCKER_NETWORK], cwd=ROOT)


def stop_router_container() -> None:
    subprocess.run(
        ["docker", "rm", "-f", ROUTER_CONTAINER],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["docker", "network", "rm", DOCKER_NETWORK],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def start_router_container() -> None:
    ensure_docker_available()
    stop_router_container()
    ensure_docker_network()
    run_command(["docker", "build", "--pull=false", "-t", ROUTER_IMAGE, "-f", str(DOCKERFILE), "."], cwd=ROOT)
    run_command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            ROUTER_CONTAINER,
            "--network",
            DOCKER_NETWORK,
            "-p",
            "12000:12000",
            "-p",
            "12001:12001",
            ROUTER_IMAGE,
        ],
        cwd=ROOT,
    )
    await wait_for_health("https://localhost:12001/health", verify=False)


async def start_example_app(app_port: int) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.setdefault("CRANKER_ROUTER_URL", "wss://localhost:12001")
    env.setdefault("CRANKER_VERIFY_SSL", "false")

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
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        cwd=ROOT,
        env=env,
        text=True,
    )
    await wait_for_health(f"http://127.0.0.1:{app_port}/health", verify=True)
    await wait_for_registration("https://localhost:12001/health/connectors")
    return server


def stop_example_app(server: subprocess.Popen[str]) -> None:
    if server.poll() is None:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


async def start_java_example_app(app_port: int) -> str:
    subprocess.run(
        ["docker", "rm", "-f", JAVA_APP_CONTAINER],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run_command(["docker", "build", "--pull=false", "-t", JAVA_APP_IMAGE, "-f", str(JAVA_APP_DOCKERFILE), "."], cwd=ROOT)
    run_command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            JAVA_APP_CONTAINER,
            "--network",
            DOCKER_NETWORK,
            "-e",
            "CRANKER_ROUTER_URL=wss://fastcc-router-test:12001",
            "-e",
            f"FASTCC_JAVA_APP_PORT={app_port}",
            "-p",
            f"{app_port}:{app_port}",
            JAVA_APP_IMAGE,
        ],
        cwd=ROOT,
    )
    await wait_for_health(f"http://127.0.0.1:{app_port}/health", verify=True)
    await wait_for_registration("https://localhost:12001/health/connectors")
    return JAVA_APP_CONTAINER


def stop_java_example_app(server: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", JAVA_APP_CONTAINER],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
