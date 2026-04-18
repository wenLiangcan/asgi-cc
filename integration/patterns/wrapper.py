from fastapi import FastAPI
from fastcc import CrankerConnector, CrankerConnectorConfig
import os

app = FastAPI()

@app.get("/hello")
async def hello():
    return {"message": "hello from wrapper"}

config = CrankerConnectorConfig(
    router_urls=[os.environ.get("CRANKER_ROUTER_URL", "wss://localhost:12001")],
    route="*",
    verify_ssl=False,
    component_name="wrapper-pattern",
)

# The connector wraps the app
connector = CrankerConnector(app, config=config)

# Entry point for uvicorn is 'connector'
app = connector
