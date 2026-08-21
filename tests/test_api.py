import threading
from pathlib import Path

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


class JsonRuntime(FakeRuntime):
    def __init__(self, content):
        super().__init__()
        self.content = content

    def convert(self, filepath, options):
        return ConversionResult(options.output_format, self.content, "application/json", 0.01)


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


def test_version_reports_contract_and_vlm_identity():
    app = create_app(
        Settings(marker_use_llm=True, marker_openai_model="test-model"),
        runtime=FakeRuntime(),
        vlm_checker=FakeHealth(),
    )
    with TestClient(app) as client:
        response = client.get("/version")
        assert response.status_code == 200
        payload = response.json()
        assert payload["markerserve_version"] == "0.1.0"
        assert payload["api_schema_version"] == "1"
        assert payload["marker_pdf_version"] == "2.0.0"
        assert payload["vlm_model"] == "test-model"


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


def test_unknown_conversion_field_is_rejected():
    app = create_app(Settings(marker_use_llm=False), runtime=FakeRuntime(), vlm_checker=FakeHealth())
    with TestClient(app) as client:
        response = client.post(
            "/v1/convert",
            files={"file": ("input.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
            data={"paginate_output": "true"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unknown_conversion_options"
        assert response.json()["error"]["details"]["fields"] == ["paginate_output"]


def test_json_conversion_returns_direct_marker_document():
    fixture_path = Path(__file__).parent / "fixtures" / "marker_json_output_v1.json"
    content = fixture_path.read_text(encoding="utf-8")
    app = create_app(
        Settings(marker_use_llm=False), runtime=JsonRuntime(content), vlm_checker=FakeHealth()
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/convert",
            files={"file": ("input.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
            data={"output_format": "json"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["children"][0]["id"] == "/page/0"
        assert "success" not in response.json()


def test_invalid_json_output_is_rejected():
    app = create_app(
        Settings(marker_use_llm=False), runtime=JsonRuntime("not-json"), vlm_checker=FakeHealth()
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/convert",
            files={"file": ("input.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
            data={"output_format": "json"},
        )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "invalid_json_output"


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
