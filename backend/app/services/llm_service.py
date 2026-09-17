"""LLM abstraction and resilient Ollama text generation client."""

import json
import time
from collections.abc import Callable
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class LLMServiceError(RuntimeError):
    pass


class LLMConnectionError(LLMServiceError):
    pass


class LLMHTTPError(LLMServiceError):
    pass


class LLMMalformedResponseError(LLMServiceError):
    pass


class LLMService(Protocol):
    def generate(self, prompt: str, *, system: str | None = None) -> str: ...

    def generate_structured(
        self,
        prompt: str,
        schema: type[StructuredOutputT],
        *,
        system: str | None = None,
    ) -> StructuredOutputT: ...


class OllamaLLMService:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        temperature: float = 0.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not model.strip():
            raise ValueError("An Ollama model name is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.temperature = temperature
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OllamaLLMService":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload = self._build_payload(prompt=prompt, system=system)
        return self._generate_response(payload)

    def generate_structured(
        self,
        prompt: str,
        schema: type[StructuredOutputT],
        *,
        system: str | None = None,
    ) -> StructuredOutputT:
        if not issubclass(schema, BaseModel):
            raise TypeError("Structured output schema must be a Pydantic model")
        payload = self._build_payload(prompt=prompt, system=system)
        payload["format"] = schema.model_json_schema()
        generated_text = self._generate_response(payload)
        try:
            decoded = json.loads(generated_text)
        except json.JSONDecodeError as error:
            raise LLMMalformedResponseError(
                "Ollama returned malformed JSON for structured generation"
            ) from error
        try:
            return schema.model_validate(decoded)
        except ValidationError as error:
            raise LLMMalformedResponseError(
                "Ollama JSON did not match the requested schema"
            ) from error

    def _build_payload(self, *, prompt: str, system: str | None) -> dict[str, object]:
        if not prompt.strip():
            raise ValueError("A generation prompt is required")
        payload: dict[str, object] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if system is not None:
            payload["system"] = system
        return payload

    def _generate_response(self, payload: dict[str, object]) -> str:
        response = self._post_with_retries(payload)
        try:
            body = response.json()
        except json.JSONDecodeError as error:
            raise LLMMalformedResponseError(
                "Ollama returned a non-JSON response"
            ) from error
        if not isinstance(body, dict):
            raise LLMMalformedResponseError("Ollama response must be a JSON object")
        generated_text = body.get("response")
        if not isinstance(generated_text, str) or not generated_text.strip():
            raise LLMMalformedResponseError(
                "Ollama response did not contain generated text"
            )
        if body.get("done") is not True:
            raise LLMMalformedResponseError("Ollama generation did not complete")
        return generated_text

    def _post_with_retries(self, payload: dict[str, object]) -> httpx.Response:
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._client.post(
                    f"{self.base_url}/api/generate", json=payload
                )
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if attempt + 1 < attempts:
                    self._wait_before_retry(attempt)
                    continue
                raise LLMConnectionError(
                    f"Ollama request failed after {attempts} attempt(s)"
                ) from error

            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < attempts:
                    self._wait_before_retry(attempt)
                    continue
                raise LLMHTTPError(
                    f"Ollama returned HTTP {response.status_code} after "
                    f"{attempts} attempt(s)"
                )
            if response.is_error:
                raise LLMHTTPError(self._http_error_message(response))
            return response
        raise AssertionError("Retry loop exited unexpectedly")

    def _wait_before_retry(self, attempt: int) -> None:
        self._sleep(self.retry_backoff_seconds * (2**attempt))

    @staticmethod
    def _http_error_message(response: httpx.Response) -> str:
        try:
            detail = response.json().get("error")
        except (json.JSONDecodeError, AttributeError):
            detail = None
        message = f"Ollama returned HTTP {response.status_code}"
        if isinstance(detail, str) and detail:
            message = f"{message}: {detail}"
        return message
