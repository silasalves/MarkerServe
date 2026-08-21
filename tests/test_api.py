import threading

from fastapi.testclient import TestClient

from app.config import Settings
from app.health import VlmCheck
from app.main import create_app
from app.marker_runtime import ConversionResult


class FakeRuntime:
    initialization_error = None
    marker_version = "2.0.0"

    def __init__(self):
        self.initialized = False

    def initialize(self):
        self.initialized = True

    def is_ready(self):
        return self.initialized

    def convert(self, filepath, options):
        return ConversionResult(options.output_format, "# Test output", "text/markdown; charset=utf-8", 0.01)


class FakeHealth:
    async def check(self, settings):
        return VlmCheck(True, {"required": True})


class UnavailableHealth:
    async def check(self, settings):
        return VlmCheck(False, {"required": True, "reason": "offline"})


class BlockingRuntime(FakeRuntime):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def convert(self, filepath, options):
        self.started.set()
        self.release.wait(timeout=5)
        return super().convert(filepath, options)


def test_live_and_ready_endpoints():
    runtime = FakeRuntime()
    app = create_app(Settings(marker_use_llm=False), runtime=runtime, vlm_checker=FakeHealth())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


def test_conversion_rejects_non_pdf():
    app = create_app(Settings(marker_use_llm=False), runtime=FakeRuntime(), vlm_checker=FakeHealth())
    with TestClient(app) as client:
        response = client.post(
            "/v1/convert",
            files={"file": ("notes.txt", b"not a pdf", "text/plain")},
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_file"


def test_conversion_cleans_up_and_returns_markdown():
    app = create_app(Settings(marker_use_llm=False), runtime=FakeRuntime(), vlm_checker=FakeHealth())
    with TestClient(app) as client:
        response = client.post(
            "/v1/convert",
            files={"file": ("input.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
        )
        assert response.status_code == 200
        assert response.text == "# Test output"
        assert response.headers["x-markerserve-output-format"] == "markdown"


def test_readiness_reports_unavailable_vlm():
    app = create_app(Settings(marker_use_llm=True), runtime=FakeRuntime(), vlm_checker=UnavailableHealth())
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["details"]["vlm"]["reason"] == "offline"


def test_second_conversion_is_rejected_while_first_is_running():
    runtime = BlockingRuntime()
    app = create_app(Settings(marker_use_llm=False), runtime=runtime, vlm_checker=FakeHealth())
    with TestClient(app) as client:
        first_result = {}

        def send_first():
            first_result["response"] = client.post(
                "/v1/convert",
                files={"file": ("first.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
            )

        worker = threading.Thread(target=send_first)
        worker.start()
        assert runtime.started.wait(timeout=2)
        second = client.post(
            "/v1/convert",
            files={"file": ("second.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
        )
        runtime.release.set()
        worker.join(timeout=5)
        assert second.status_code == 429
        assert first_result["response"].status_code == 200
