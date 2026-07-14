from types import SimpleNamespace

import pytest

from core.config import ModelConfig
from core.llm_processor import LLMProcessor


class FakeCompletions:
    def __init__(self, client):
        self.client = client
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content=self.client.response)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self):
        self.response = "clean"
        self.chat = SimpleNamespace(completions=FakeCompletions(self))


@pytest.fixture
def model_config():
    return ModelConfig(
        api_key="test-key",
        base_url="https://example.invalid/litellm",
        model="example-model",
    )


@pytest.fixture
def fake_client():
    return FakeClient()


def test_sends_configured_model_and_max_tokens(model_config, fake_client):
    processor = LLMProcessor(
        {"nanyan": model_config},
        max_tokens=128000,
        client_factory=lambda **kwargs: fake_client,
    )

    result = processor.structured_refine("input", "nanyan")

    request = fake_client.chat.completions.requests[0]
    assert request["model"] == "example-model"
    assert request["max_tokens"] == 128000
    assert request["messages"][0]["content"].endswith("input")
    assert result == "clean"


def test_configures_client_with_transient_gateway_retry_budget(model_config):
    created_with = []

    def client_factory(**kwargs):
        created_with.append(kwargs)
        return FakeClient()

    processor = LLMProcessor(
        {"nanyan": model_config},
        client_factory=client_factory,
    )

    processor.structured_refine("input", "nanyan")

    assert created_with[0]["max_retries"] == 5


def test_custom_http_client_keeps_transient_gateway_retry_budget(
    model_config, monkeypatch
):
    model_config.extra_headers = {"X-Test": "value"}
    model_config.verify_ssl = False
    http_client = object()
    monkeypatch.setattr(
        "core.llm_processor.httpx.Client", lambda **kwargs: http_client
    )
    created_with = []

    def client_factory(**kwargs):
        created_with.append(kwargs)
        return FakeClient()

    processor = LLMProcessor(
        {"nanyan": model_config},
        client_factory=client_factory,
    )

    processor.structured_refine("input", "nanyan")

    assert created_with[0]["http_client"] is http_client
    assert created_with[0]["max_retries"] == 5


def test_removes_thinking_blocks(model_config, fake_client):
    fake_client.response = "<think>secret reasoning</think>clean"
    processor = LLMProcessor(
        {"nanyan": model_config},
        max_tokens=128000,
        client_factory=lambda **kwargs: fake_client,
    )

    assert processor.structured_refine("input", "nanyan") == "clean"


def test_refine_entrypoints_share_only_structured_prompt(model_config, fake_client):
    processor = LLMProcessor(
        {"nanyan": model_config},
        client_factory=lambda **kwargs: fake_client,
    )

    processor.refine("input", "nanyan")
    processor.structured_refine("input", "nanyan")

    prompts = [
        request["messages"][0]["content"]
        for request in fake_client.chat.completions.requests
    ]
    expected = LLMProcessor.STRUCTURED_REFINE_PROMPT.format(text="input")
    assert prompts == [expected, expected]
    assert "每个子部分末尾添加以“结论：”开头的结论段落" in expected
    assert not hasattr(LLMProcessor, "PROMPT_REFINE")
