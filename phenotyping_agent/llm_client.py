"""LLM client factory for instantiating configured language models."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from langchain_openai import AzureChatOpenAI, ChatOpenAI

if TYPE_CHECKING:
    from langchain_core.language_model import BaseLanguageModel

from phenotyping_agent.config import ModelTier


def _get_openai_client(tier: ModelTier) -> Any:
    """Instantiate OpenAI ChatOpenAI client.

    Expects environment variables:
    - OPENAI_API_KEY: API key for OpenAI
    - OPENAI_API_VERSION: (optional) API version, defaults to "2024-08-01"
    - OPENAI_BASE_URL: (optional) Base URL for proxy/self-hosted endpoints
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable not set. "
            "Visit https://platform.openai.com/account/api-keys to create a key."
        )

    return ChatOpenAI(
        model=tier.model,
        api_key=api_key,  # type: ignore[arg-type]
        base_url=os.getenv("OPENAI_BASE_URL"),
        temperature=0.2,
        top_p=0.9,
        max_tokens=4096,
    )


def _get_azure_openai_client(tier: ModelTier) -> Any:
    """Instantiate Azure OpenAI ChatOpenAI client.

    Expects environment variables:
    - AZURE_OPENAI_API_KEY: API key for Azure OpenAI
    - AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint URL
    - AZURE_OPENAI_API_VERSION: API version (defaults to "2024-08-01")
    - AZURE_OPENAI_DEPLOYMENT_NAME: Deployment name (defaults to model tier name)
    """
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not api_key or not endpoint:
        raise ValueError(
            "AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set. "
            "Visit https://learn.microsoft.com/en-us/azure/cognitive-services/openai/how-to/create-resource"
        )

    return AzureChatOpenAI(
        model=tier.model,
        api_key=api_key,  # type: ignore[arg-type]
        azure_endpoint=endpoint,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01"),
        deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", tier.model),  # type: ignore[arg-type]
        temperature=0.2,
        top_p=0.9,
        max_tokens=4096,
    )


def _get_anthropic_client(tier: ModelTier) -> Any:
    """Instantiate Anthropic Claude client.

    Expects environment variables:
    - ANTHROPIC_API_KEY: API key for Anthropic
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError(
            "langchain-anthropic not installed. "
            "Install with: pip install langchain-anthropic"
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Visit https://console.anthropic.com/account/keys to create a key."
        )

    return ChatAnthropic(
        model=tier.model,
        api_key=api_key,  # type: ignore[arg-type]
        temperature=0.2,
        max_tokens=4096,
    )


def get_llm_client(tier: ModelTier) -> Any:
    """Factory function to get an LLM client based on ModelTier configuration.

    Args:
        tier: ModelTier instance with provider and model name

    Returns:
        Instantiated language model client (ChatOpenAI, AzureChatOpenAI, or ChatAnthropic)

    Raises:
        ValueError: If required environment variables are missing
        ImportError: If required dependencies are not installed

    Examples:
        >>> tier = ModelTier(provider="openai", model="gpt-4o")
        >>> llm = get_llm_client(tier)

        >>> tier = ModelTier(provider="azure_openai", model="gpt-4-deployment")
        >>> llm = get_llm_client(tier)

        >>> tier = ModelTier(provider="anthropic", model="claude-3-5-sonnet-20241022")
        >>> llm = get_llm_client(tier)
    """
    if tier.provider == "openai":
        return _get_openai_client(tier)
    elif tier.provider == "azure_openai":
        return _get_azure_openai_client(tier)
    elif tier.provider == "anthropic":
        return _get_anthropic_client(tier)
    elif tier.provider == "none":
        raise ValueError(
            f"LLM provider is set to 'none'. "
            "Configure real models: --reasoning-tier provider --reasoning-model model-name"
        )
    else:
        raise ValueError(
            f"Unknown LLM provider: {tier.provider}. "
            "Supported: 'openai', 'azure_openai', 'anthropic'"
        )









