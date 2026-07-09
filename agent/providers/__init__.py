"""Provider factory — returns the configured provider instance."""

from .base import BaseProvider


def get_provider(config) -> BaseProvider:
    """Create a provider based on config.PROVIDER."""
    kind = config.PROVIDER.lower()

    if kind == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(model=config.MODEL, api_key=config.API_KEY)

    elif kind == "openai_compat":
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(
            model=config.MODEL,
            api_key=config.API_KEY,
            base_url=getattr(config, "API_BASE", ""),
        )

    elif kind == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(
            model=config.MODEL,
            ollama_url=getattr(config, "OLLAMA_URL", "http://localhost:11434"),
        )

    else:
        raise ValueError(
            f"Unknown provider: {kind}. Choose: anthropic, openai_compat, ollama"
        )
