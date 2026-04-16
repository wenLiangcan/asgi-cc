from __future__ import annotations

import asyncio
import os
import httpx
from fastapi import FastAPI
from fastcc import CrankerConnector, CrankerConnectorConfig
from integration.common import start_router_container, stop_router_container

async def test_runtime_attach_detach():
    print("Starting router container...")
    await start_router_container()
    
    config = CrankerConnectorConfig(
        router_urls=["wss://localhost:12001"],
        route="*",
        verify_ssl=False,
        component_name="runtime-test",
    )
    
    print("Starting connector without app...")
    connector = CrankerConnector(config=config)
    await connector.startup()
    
    try:
        async with httpx.AsyncClient(verify=False, timeout=5) as client:
            print("1. Testing 503 when no app attached...")
            await asyncio.sleep(2) 
            
            resp = await client.get("https://localhost:12000/hello")
            assert resp.status_code == 503
            assert "No app attached" in resp.text
            print("   OK")
            
            print("2. Attaching first app...")
            app = FastAPI()
            @app.get("/hello")
            async def hello():
                return {"message": "hello runtime"}
            
            connector.attach(app)
            
            resp = await client.get("https://localhost:12000/hello")
            assert resp.status_code == 200
            assert resp.json() == {"message": "hello runtime"}
            print("   OK")
            
            print("3. Detaching app...")
            connector.detach()
            resp = await client.get("https://localhost:12000/hello")
            assert resp.status_code == 503
            print("   OK")
            
            print("4. Attaching second app...")
            app2 = FastAPI()
            @app2.get("/hello")
            async def hello2():
                return {"message": "hello again"}
            
            connector.attach(app2)
            resp = await client.get("https://localhost:12000/hello")
            assert resp.status_code == 200
            assert resp.json() == {"message": "hello again"}
            print("   OK")

    finally:
        print("Shutting down...")
        await connector.shutdown()
        stop_router_container()

if __name__ == "__main__":
    asyncio.run(test_runtime_attach_detach())
