"""LLM client factory for instantiating configured language models."""

from __future__ import annotations

import os
import time
from uuid import uuid4
from typing import Any

import re

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import SecretStr

from phenotyping_agent.config import ModelTier
from phenotyping_agent.llm_events import LLMEventLogger, extract_text, extract_usage

# Output-token ceiling for every provider. 4096 was tight enough that a long design or report
# could be truncated mid-JSON, which surfaces as an opaque structured-output parse failure.
# Override with LLM_MAX_OUTPUT_TOKENS if your deployment allows less (or more).
MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "32000"))

# Reasoning models (o-series, gpt-5) reject `temperature` and `top_p`: the API only accepts the
# default sampling settings and returns a 400 `unsupported_value` otherwise.
_REASONING_MODEL_RE = re.compile(r"^(o\d|gpt-5)", re.IGNORECASE)

# Azure endpoints are sometimes handed out as the full chat-completions URL, e.g.
# https://host/openai-chat/openai/deployments/o3/. langchain appends
# `/openai/deployments/<deployment>/chat/completions` itself, so passing the long form yields a
# doubled path and an opaque 404 "Resource not found" (surfaced as OpenAIModelNotFoundError).
_AZURE_DEPLOYMENT_PATH_RE = re.compile(
    r"/openai/deployments/(?P<deployment>[^/?#]+).*$", re.IGNORECASE
)


def _is_reasoning_model(model: str) -> bool:
    return bool(_REASONING_MODEL_RE.match(model.strip()))


def _sampling_kwargs(model: str) -> dict[str, Any]:
    """Sampling parameters that the given model actually accepts."""
    if _is_reasoning_model(model):
        return {}
    return {"temperature": 0.2, "top_p": 0.9}


def _split_azure_endpoint(endpoint: str) -> tuple[str, str | None]:
    """Split an Azure endpoint into (base endpoint, deployment name embedded in the URL)."""
    endpoint = endpoint.strip().rstrip("/")
    match = _AZURE_DEPLOYMENT_PATH_RE.search(endpoint)
    if not match:
        return endpoint, None
    return endpoint[: match.start()], match.group("deployment")


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
        max_tokens=MAX_OUTPUT_TOKENS,
        **_sampling_kwargs(tier.model),
    )


def _get_azure_openai_client(tier: ModelTier) -> Any:
    """Instantiate Azure OpenAI ChatOpenAI client.

    Expects environment variables:
    - AZURE_OPENAI_API_KEY: API key for Azure OpenAI
    - AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint URL. Either the resource base
      (https://your-resource.openai.azure.com) or a full deployment URL
      (https://.../openai/deployments/<name>/...); the deployment suffix is stripped and, when no
      deployment is configured elsewhere, used as the deployment name.
    - AZURE_OPENAI_API_VERSION: API version (defaults to "2024-08-01")
    - AZURE_OPENAI_DEPLOYMENT_NAME / AZURE_OPENAI_DEPLOYMENT: Deployment name override
      (defaults to the model tier name, then to the deployment embedded in the endpoint)
    """
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not api_key or not endpoint:
        raise ValueError(
            "AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set. "
            "Visit https://learn.microsoft.com/en-us/azure/cognitive-services/openai/how-to/create-resource"
        )

    base_endpoint, endpoint_deployment = _split_azure_endpoint(endpoint)
    # The per-tier model name wins: a single global deployment variable cannot describe two tiers
    # pointing at different deployments.
    deployment = (
        tier.model
        or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or endpoint_deployment
    )
    if not deployment:
        raise ValueError(
            "No Azure OpenAI deployment configured. Set AZURE_OPENAI_DEPLOYMENT_NAME or a tier "
            "model name (e.g. REASONING_TIER_MODEL)."
        )

    return AzureChatOpenAI(
        model=tier.model or deployment,
        api_key=api_key,  # type: ignore[arg-type]
        azure_endpoint=base_endpoint,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01"),
        deployment_name=deployment,  # type: ignore[arg-type]
        max_tokens=MAX_OUTPUT_TOKENS,
        **_sampling_kwargs(tier.model or deployment),
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
        max_tokens=MAX_OUTPUT_TOKENS,
    )


def _get_bedrock_client(tier: ModelTier) -> Any:
    """Instantiate a standard AWS or J&J gateway Bedrock client.

    Expects environment variables:
    - Optional BEDROCK_API_KEY: enables the API-key-authenticated J&J gateway
    - Optional BEDROCK_BASE_URL: gateway URL (defaults to the J&J gateway when an API key is set)
    - Optional BEDROCK_ANTHROPIC_VERSION: gateway payload version
    - BEDROCK_AWS_REGION or AWS_REGION / AWS_DEFAULT_REGION: AWS region for Bedrock
    - Optional BEDROCK_AWS_PROFILE / AWS_PROFILE: named AWS credentials profile
    - Optional AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN: explicit AWS creds

    Standard AWS credential resolution also works (shared config, SSO, instance/container roles).
    """
    model = tier.model.strip()
    if not model:
        raise ValueError(
            "No Amazon Bedrock model configured. Set the tier model to a Bedrock model ID, "
            "for example 'anthropic.claude-3-opus-20240229-v1:0'."
        )

    gateway_api_key = os.getenv("BEDROCK_API_KEY")
    gateway_base_url = os.getenv("BEDROCK_BASE_URL")
    if gateway_api_key or gateway_base_url:
        if not gateway_api_key:
            raise ValueError(
                "BEDROCK_API_KEY must be set when using the custom BEDROCK_BASE_URL gateway."
            )
        from phenotyping_agent.jnj_bedrock import JnjBedrockChat

        return JnjBedrockChat(
            model=model,
            api_key=SecretStr(gateway_api_key),
            base_url=gateway_base_url or "https://genaiapigwna.jnj.com",
            anthropic_version=os.getenv("BEDROCK_ANTHROPIC_VERSION", "bedrock-2023-05-31"),
            max_tokens=MAX_OUTPUT_TOKENS,
        )

    try:
        from langchain_aws import ChatBedrockConverse
    except ImportError:
        raise ImportError(
            "langchain-aws not installed. "
            "Install with: pip install langchain-aws"
        )


    region = (
        os.getenv("BEDROCK_AWS_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
    )
    if not region:
        raise ValueError(
            "Amazon Bedrock region not configured. Set BEDROCK_AWS_REGION, AWS_REGION, "
            "or AWS_DEFAULT_REGION."
        )

    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    session_token = os.getenv("AWS_SESSION_TOKEN")
    profile = os.getenv("BEDROCK_AWS_PROFILE") or os.getenv("AWS_PROFILE")

    client_kwargs: dict[str, Any] = {
        "model": model,
        "region_name": region,
        "max_tokens": MAX_OUTPUT_TOKENS,
        **_sampling_kwargs(model),
    }
    if profile:
        client_kwargs["credentials_profile_name"] = profile
    if access_key or secret_key or session_token:
        if not access_key or not secret_key:
            raise ValueError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must both be set when using "
                "explicit AWS credentials for Amazon Bedrock."
            )
        client_kwargs["aws_access_key_id"] = access_key
        client_kwargs["aws_secret_access_key"] = secret_key
        if session_token:
            client_kwargs["aws_session_token"] = session_token

    return ChatBedrockConverse(**client_kwargs)


def get_llm_client(tier: ModelTier) -> Any:
    """Factory function to get an LLM client based on ModelTier configuration.

    Args:
        tier: ModelTier instance with provider and model name

    Returns:
        Instantiated language model client (ChatOpenAI, AzureChatOpenAI, ChatAnthropic,
        or ChatBedrockConverse)

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

        >>> tier = ModelTier(provider="bedrock", model="anthropic.claude-3-opus-20240229-v1:0")
        >>> llm = get_llm_client(tier)
    """
    if tier.provider == "openai":
        return _get_openai_client(tier)
    elif tier.provider == "azure_openai":
        return _get_azure_openai_client(tier)
    elif tier.provider == "anthropic":
        return _get_anthropic_client(tier)
    elif tier.provider == "bedrock":
        return _get_bedrock_client(tier)
    elif tier.provider == "none":
        raise ValueError(
            f"LLM provider is set to 'none'. "
            "Configure real models: --reasoning-tier provider --reasoning-model model-name"
        )
    else:
        raise ValueError(
            f"Unknown LLM provider: {tier.provider}. "
            "Supported: 'openai', 'azure_openai', 'anthropic', 'bedrock'"
        )


def invoke_with_logging(
    client: Any,
    messages: Any,
    *,
    event_logger: LLMEventLogger,
    tier: ModelTier,
    node: str,
    prompt_template: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Invoke an LLM client and append request/response details to llm_events.jsonl."""
    request_id = str(uuid4())
    started_at = time.perf_counter()
    base_event = {
        "event": "llm_response",
        "request_id": request_id,
        "provider": tier.provider,
        "model": tier.model,
        "node": node,
        "prompt_template": prompt_template,
        "metadata": metadata or {},
        "input_text": extract_text(messages),
    }
    try:
        response = client.invoke(messages)
    except Exception as exc:
        event_logger.append(
            {
                **base_event,
                "event": "llm_error",
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "error": str(exc),
            }
        )
        raise

    response_metadata = getattr(response, "response_metadata", None)
    finish_reason = None
    if isinstance(response_metadata, dict):
        finish_reason = response_metadata.get("finish_reason")
    event_logger.append(
        {
            **base_event,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
            "output_text": extract_text(response),
            "usage": extract_usage(response),
            "finish_reason": finish_reason,
            "error": None,
        }
    )
    return response










