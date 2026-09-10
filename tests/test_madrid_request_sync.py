import asyncio
import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "madrid_request_sync",
    Path("sites/madrid/flows/sync.py"),
)
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)
install_madrid_request_sync = SYNC.install_madrid_request_sync


class FakePage:
    def __init__(self) -> None:
        self.handlers = {}

    def on(self, event, callback) -> None:
        self.handlers[event] = callback

    def emit(self, event, request) -> None:
        self.handlers[event](request)

    async def wait_for_timeout(self, milliseconds: int) -> None:
        await asyncio.sleep(milliseconds / 1000)


class FakeRequest:
    def __init__(self, *, method="POST", resource_type="xhr", url="") -> None:
        self.method = method
        self.resource_type = resource_type
        self.url = url


def test_madrid_sync_waits_for_pending_wfors_request() -> None:
    async def scenario() -> None:
        page = FakePage()
        tracker = install_madrid_request_sync(page)
        request = FakeRequest(url="https://servcla.madrid.es/WFORS_WBWFORS/formClientServlet")

        page.emit("request", request)
        waiter = asyncio.create_task(
            tracker.wait_until_idle(page, label="test", timeout_ms=500, quiet_ms=10)
        )
        await asyncio.sleep(0.02)
        assert not waiter.done()

        page.emit("requestfinished", request)
        await waiter
        assert tracker.pending_count == 0

    asyncio.run(scenario())


def test_madrid_sync_ignores_non_wfors_traffic() -> None:
    async def scenario() -> None:
        page = FakePage()
        tracker = install_madrid_request_sync(page)
        request = FakeRequest(
            method="GET",
            resource_type="image",
            url="https://servcla.madrid.es/assets/logo.png",
        )

        page.emit("request", request)
        await tracker.wait_until_idle(page, label="test", timeout_ms=200, quiet_ms=10)
        assert tracker.pending_count == 0

    asyncio.run(scenario())
