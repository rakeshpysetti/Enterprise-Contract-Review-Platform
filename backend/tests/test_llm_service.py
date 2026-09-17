import json

import httpx
import pytest
from pydantic import BaseModel, Field

from app.services.llm_service import (
    LLMConnectionError,
    LLMHTTPError,
    LLMMalformedResponseError,
    OllamaLLMService,
)


class ExtractedParty(BaseModel):
    name: str
    confidence: float = Field(ge=0, le=1)


def make_service(handler, *, retries=2, sleeps=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaLLMService(
        base_url="http://ollama:11434/",
        model="test-model",
        timeout_seconds=3,
        max_retries=retries,
        retry_backoff_seconds=0.25,
        temperature=0.1,
        client=client,
        sleep=(sleeps.append if sleeps is not None else lambda _delay: None),
    )


def test_text_generation_sends_configured_ollama_request():
    def handler(request: httpx.Request):
        assert request.url == "http://ollama:11434/api/generate"
        payload = json.loads(request.content)
        assert payload == {
            "model": "test-model",
            "prompt": "Summarize the contract",
            "system": "Be concise",
            "stream": False,
            "options": {"temperature": 0.1},
        }
        return httpx.Response(200, json={"response": "Summary", "done": True})

    assert make_service(handler).generate(
        "Summarize the contract", system="Be concise"
    ) == "Summary"


def test_structured_generation_sends_schema_and_validates_result():
    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        assert payload["format"] == ExtractedParty.model_json_schema()
        return httpx.Response(
            200,
            json={
                "response": '{"name":"Acme Corp","confidence":0.98}',
                "done": True,
            },
        )

    result = make_service(handler).generate_structured(
        "Extract the counterparty", ExtractedParty
    )
    assert result == ExtractedParty(name="Acme Corp", confidence=0.98)


@pytest.mark.parametrize(
    "ollama_response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"done": True}),
        httpx.Response(200, json={"response": "", "done": True}),
        httpx.Response(200, json={"response": "partial", "done": False}),
    ],
)
def test_text_generation_rejects_malformed_responses(ollama_response):
    with pytest.raises(LLMMalformedResponseError):
        make_service(lambda _request: ollama_response).generate("Prompt")


@pytest.mark.parametrize(
    "generated_text",
    [
        "not json",
        '```json\n{"name":"Acme Corp","confidence":0.9}\n```',
        '{"name":"Acme Corp","confidence":2}',
        '{"name":42,"confidence":0.9}',
    ],
)
def test_structured_generation_rejects_malformed_or_invalid_json(generated_text):
    service = make_service(
        lambda _request: httpx.Response(
            200, json={"response": generated_text, "done": True}
        )
    )
    with pytest.raises(LLMMalformedResponseError):
        service.generate_structured("Extract", ExtractedParty)


def test_transient_errors_are_retried_with_exponential_backoff():
    attempts = 0
    sleeps = []

    def handler(_request: httpx.Request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("slow")
        if attempts == 2:
            return httpx.Response(503, json={"error": "loading model"})
        return httpx.Response(200, json={"response": "Ready", "done": True})

    assert make_service(handler, sleeps=sleeps).generate("Prompt") == "Ready"
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_retry_exhaustion_raises_connection_error():
    service = make_service(
        lambda _request: (_ for _ in ()).throw(httpx.ConnectError("offline")),
        retries=1,
    )
    with pytest.raises(LLMConnectionError, match="2 attempt"):
        service.generate("Prompt")


def test_retry_exhaustion_raises_http_error():
    service = make_service(
        lambda _request: httpx.Response(429, json={"error": "busy"}), retries=1
    )
    with pytest.raises(LLMHTTPError, match="429.*2 attempt"):
        service.generate("Prompt")


def test_non_retryable_error_includes_ollama_message_once():
    attempts = 0

    def handler(_request: httpx.Request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(LLMHTTPError, match="404: model not found"):
        make_service(handler).generate("Prompt")
    assert attempts == 1


def test_blank_prompt_and_invalid_configuration_are_rejected():
    service = make_service(
        lambda _request: httpx.Response(200, json={"response": "x", "done": True})
    )
    with pytest.raises(ValueError, match="prompt"):
        service.generate("   ")
    with pytest.raises(ValueError, match="model"):
        OllamaLLMService(base_url="http://localhost", model="")
