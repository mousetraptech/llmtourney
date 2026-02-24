"""OpenRouter adapter -- thin subclass of OpenAIAdapter.

Sets base_url to OpenRouter's endpoint and optionally adds
attribution headers (HTTP-Referer, X-Title).
"""

from llmtourney.core.openai_adapter import OpenAIAdapter

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterAdapter(OpenAIAdapter):
    """Adapter for OpenRouter -- uses the OpenAI-compatible API."""

    def __init__(
        self,
        model_id: str,
        api_key: str,
        temperature: float = 0.0,
        site_url: str | None = None,
        app_name: str | None = None,
    ):
        extra_headers: dict[str, str] = {}
        if site_url:
            extra_headers["HTTP-Referer"] = site_url
        if app_name:
            extra_headers["X-Title"] = app_name

        super().__init__(
            model_id=model_id,
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            temperature=temperature,
            extra_headers=extra_headers if extra_headers else None,
        )
