from fastapi import FastAPI
from fastcc import CrankerConnector, CrankerConnectorConfig
import os

app = FastAPI()

config = CrankerConnectorConfig(
    router_urls=[os.environ.get("CRANKER_ROUTER_URL", "wss://localhost:12001")],
    route="*",
    verify_ssl=False,
    component_name="middleware-pattern",
)

# The connector is added as standard middleware
app.add_middleware(CrankerConnector, config=config)

@app.get("/hello")
async def hello():
    return {"message": "hello from middleware"}
