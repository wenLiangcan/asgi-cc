import os

from fastapi import FastAPI

from asgi_cc import CrankerConnector, CrankerConnectorConfig

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

# The connector attaches to the app lifecycle hooks.
connector = CrankerConnector(app, config=config)
