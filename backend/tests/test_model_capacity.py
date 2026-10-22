from concurrent.futures import ThreadPoolExecutor
from threading import Event

from app.api.dependencies import LLMServiceDependency
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


class BlockingModel:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def generate(self, prompt: str) -> str:
        self.entered.set()
        assert self.release.wait(timeout=5)
        return prompt


def test_model_capacity_rejects_busy_request_and_recovers() -> None:
    app = create_app(
        Settings(_env_file=None, app_env="test", max_concurrent_model_requests=1)
    )
    model = BlockingModel()
    app.state.llm_service = model

    @app.get("/model-capacity-probe")
    def probe(llm: LLMServiceDependency) -> dict[str, str]:
        return {"answer": llm.generate("ready")}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.get, "/model-capacity-probe")
        assert model.entered.wait(timeout=5)
        busy = client.get("/model-capacity-probe")
        assert busy.status_code == 503
        assert busy.headers["retry-after"] == "30"
        assert client.get("/health").status_code == 200
        model.release.set()
        assert first.result(timeout=5).json() == {"answer": "ready"}
        assert client.get("/model-capacity-probe").status_code == 200
