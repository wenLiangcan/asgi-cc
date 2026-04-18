from __future__ import annotations

import asyncio
import os
import sys
import subprocess
import httpx
from integration.common import start_router_container, stop_router_container, wait_for_health, wait_for_registration

async def run_pattern_test(module: str, expected_message: str):
    print(f"\n--- Testing pattern: {module} ---")
    env = os.environ.copy()
    env["CRANKER_ROUTER_URL"] = "wss://localhost:12001"
    env["CRANKER_VERIFY_SSL"] = "false"
    
    port = 18090
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            f"integration.patterns.{module}:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        env=env,
    )
    
    try:
        await wait_for_health(f"http://127.0.0.1:{port}/hello", verify=True)
        await wait_for_registration("https://localhost:12001/health/connectors")
        
        async with httpx.AsyncClient(verify=False, timeout=5) as client:
            resp = await client.get("https://localhost:12000/hello")
            assert resp.status_code == 200
            assert resp.json() == {"message": expected_message}
            print(f"    SUCCESS: Received '{expected_message}' through router")
            
    finally:
        server.terminate()
        server.wait()

async def main():
    await start_router_container()
    try:
        await run_pattern_test("wrapper", "hello from wrapper")
        await run_pattern_test("middleware", "hello from middleware")
    finally:
        stop_router_container()

if __name__ == "__main__":
    asyncio.run(main())
