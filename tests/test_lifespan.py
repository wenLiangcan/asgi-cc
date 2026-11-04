from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.applications import Starlette

from asgi_cc import CrankerConnector, CrankerConnectorConfig


def make_connector(app):
    # No router connections are needed to exercise the application lifecycle.
    connector = CrankerConnector(
        app, CrankerConnectorConfig(router_urls=[], route="*")
    )
    connector.startup = AsyncMock(wraps=connector.startup)
    connector.shutdown = AsyncMock(wraps=connector.shutdown)
    return connector


class LifespanTests(unittest.TestCase):
    def test_framework_without_lifespan_support_logs_actionable_warning(self):
        for router in (SimpleNamespace(), SimpleNamespace(lifespan_context=None)):
            with self.subTest(router=router):
                with self.assertLogs("asgi_cc.connector", level="WARNING") as logs:
                    connector = make_connector(SimpleNamespace(router=router))
                self.assertFalse(connector._started)
                self.assertEqual(len(logs.records), 1)
                self.assertIn("lifespan_context", logs.output[0])
                self.assertIn("ASGI middleware", logs.output[0])
                self.assertIn("connector.startup()", logs.output[0])
                self.assertIn("connector.shutdown()", logs.output[0])

    def test_legacy_framework_without_router_logs_warning(self):
        with self.assertLogs("asgi_cc.connector", level="WARNING"):
            make_connector(SimpleNamespace(add_event_handler=lambda *args: None))

    def test_supported_framework_does_not_warn(self):
        with self.assertNoLogs("asgi_cc.connector", level="WARNING"):
            make_connector(FastAPI())

    def test_default_lifespan_can_be_reused(self):
        for app_type in (FastAPI, Starlette):
            with self.subTest(app_type=app_type):
                app = app_type()
                connector = make_connector(app)
                for _ in range(2):
                    with TestClient(app):
                        self.assertTrue(connector._started)
                        self.assertIs(connector.app, app)
                    self.assertFalse(connector._started)
                    self.assertIsNone(connector.app)
                self.assertEqual(connector.startup.await_count, 2)
                self.assertEqual(connector.shutdown.await_count, 2)

    def test_custom_lifespan_preserves_state_and_resource_order(self):
        events = []

        @asynccontextmanager
        async def lifespan(app):
            events.append("app startup")
            self.assertFalse(connector._started)
            yield {"resource": "ready"}
            self.assertFalse(connector._started)
            events.append("app shutdown")

        app = FastAPI(lifespan=lifespan)
        connector = make_connector(app)

        @app.get("/")
        async def resource(request: Request):
            return {"resource": request.state.resource}

        with TestClient(app) as client:
            self.assertTrue(connector._started)
            self.assertEqual(events, ["app startup"])
            self.assertEqual(client.get("/").json(), {"resource": "ready"})
        self.assertEqual(events, ["app startup", "app shutdown"])
        connector.startup.assert_awaited_once()
        connector.shutdown.assert_awaited_once()

    def test_middleware_lifecycle(self):
        app = FastAPI()
        app.add_middleware(
            CrankerConnector,
            config=CrankerConnectorConfig(router_urls=[], route="*"),
        )
        with self.assertNoLogs("asgi_cc.connector", level="WARNING"), TestClient(app):
            connector = app.middleware_stack
            while connector is not None and not isinstance(connector, CrankerConnector):
                connector = getattr(connector, "app", None)
            assert isinstance(connector, CrankerConnector)
            self.assertTrue(connector._started)
        self.assertFalse(connector._started)


class LifespanFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_attach_does_not_register_twice(self):
        app = FastAPI()
        connector = make_connector(app)
        lifespan = app.router.lifespan_context
        await connector.attach(app)
        await connector.attach(app)
        self.assertIs(app.router.lifespan_context, lifespan)
        await connector.detach()
        connector.startup.reset_mock()
        connector.shutdown.reset_mock()
        async with app.router.lifespan_context(app):
            self.assertTrue(connector._started)
        connector.startup.assert_awaited_once()
        connector.shutdown.assert_awaited_once()

    async def test_connector_cleans_up_when_lifespan_body_fails(self):
        app = FastAPI()
        connector = make_connector(app)
        with self.assertRaisesRegex(RuntimeError, "body failed"):
            async with app.router.lifespan_context(app):
                raise RuntimeError("body failed")
        self.assertFalse(connector._started)
        connector.shutdown.assert_awaited_once()

    async def test_partial_connector_startup_is_cleaned_up(self):
        app = FastAPI()
        connector = make_connector(app)
        connector._refresh_router_registrations = AsyncMock(
            side_effect=RuntimeError("registration failed")
        )
        with self.assertRaisesRegex(RuntimeError, "registration failed"):
            async with app.router.lifespan_context(app):
                self.fail("startup should have failed")
        self.assertFalse(connector._started)
        connector.shutdown.assert_awaited_once()

    async def test_app_startup_failure_does_not_start_connector(self):
        @asynccontextmanager
        async def lifespan(app):
            raise RuntimeError("app failed")
            yield

        app = FastAPI(lifespan=lifespan)
        connector = make_connector(app)
        with self.assertRaisesRegex(RuntimeError, "app failed"):
            async with app.router.lifespan_context(app):
                self.fail("startup should have failed")
        connector.startup.assert_not_awaited()
        connector.shutdown.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
