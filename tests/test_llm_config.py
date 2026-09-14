#!/usr/bin/env python3
"""Test script to validate LLM client configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add phenotyping_agent to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from phenotyping_agent.config import ModelTier
from phenotyping_agent.llm_client import get_llm_client


def test_dry_run_mode():
    """Test that dry-run mode raises appropriate error."""
    print("\n=== Test 1: Dry-Run Mode (Should Raise) ===")
    tier = ModelTier(provider="none", model="dry-run")
    try:
        client = get_llm_client(tier)
        print("❌ FAILED: Should have raised ValueError for 'none' provider")
        return False
    except ValueError as e:
        print(f"✅ PASSED: Correctly raised ValueError: {e}")
        return True


def test_openai_missing_key():
    """Test that OpenAI provider requires API key."""
    print("\n=== Test 2: OpenAI Missing Key ===")
    # Ensure key is not set
    os.environ.pop("OPENAI_API_KEY", None)

    tier = ModelTier(provider="openai", model="gpt-4o")
    try:
        client = get_llm_client(tier)
        print("❌ FAILED: Should have raised ValueError for missing API key")
        return False
    except ValueError as e:
        if "OPENAI_API_KEY" in str(e):
            print(f"✅ PASSED: Correctly raised ValueError: {e}")
            return True
        else:
            print(f"❌ FAILED: Wrong error message: {e}")
            return False


def test_azure_openai_missing_credentials():
    """Test that Azure OpenAI provider requires credentials."""
    print("\n=== Test 3: Azure OpenAI Missing Credentials ===")
    os.environ.pop("AZURE_OPENAI_API_KEY", None)
    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)

    tier = ModelTier(provider="azure_openai", model="gpt-4o-deployment")
    try:
        client = get_llm_client(tier)
        print("❌ FAILED: Should have raised ValueError for missing credentials")
        return False
    except ValueError as e:
        if "AZURE_OPENAI" in str(e):
            print(f"✅ PASSED: Correctly raised ValueError: {e}")
            return True
        else:
            print(f"❌ FAILED: Wrong error message: {e}")
            return False


def test_anthropic_missing_key():
    """Test that Anthropic provider requires API key."""
    print("\n=== Test 4: Anthropic Missing Key ===")
    os.environ.pop("ANTHROPIC_API_KEY", None)

    tier = ModelTier(provider="anthropic", model="claude-3-5-sonnet-20241022")
    try:
        client = get_llm_client(tier)
        print("❌ FAILED: Should have raised ValueError for missing API key")
        return False
    except (ValueError, ImportError) as e:
        if "ANTHROPIC_API_KEY" in str(e) or "langchain-anthropic" in str(e):
            print(f"✅ PASSED: Correctly raised error: {type(e).__name__}")
            return True
        else:
            print(f"❌ FAILED: Wrong error message: {e}")
            return False


def test_unknown_provider():
    """Test that unknown provider raises error."""
    print("\n=== Test 5: Unknown Provider ===")
    tier = ModelTier(provider="unknown", model="model")  # type: ignore[arg-type]
    try:
        client = get_llm_client(tier)
        print("❌ FAILED: Should have raised ValueError for unknown provider")
        return False
    except ValueError as e:
        if "Unknown LLM provider" in str(e):
            print(f"✅ PASSED: Correctly raised ValueError: {e}")
            return True
        else:
            print(f"❌ FAILED: Wrong error message: {e}")
            return False


def test_openai_with_key():
    """Test OpenAI client instantiation with valid key."""
    print("\n=== Test 6: OpenAI with Valid Key ===")
    os.environ["OPENAI_API_KEY"] = "sk-test-key"

    tier = ModelTier(provider="openai", model="gpt-4o")
    try:
        client = get_llm_client(tier)
        print(f"✅ PASSED: Created OpenAI client: {type(client).__name__}")
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_config_loading():
    """Test that config loads LLM settings from environment."""
    print("\n=== Test 7: Config Loading from Environment ===")
    from phenotyping_agent.config import build_config

    os.environ["REASONING_TIER_PROVIDER"] = "openai"
    os.environ["REASONING_TIER_MODEL"] = "gpt-4o"
    os.environ["FAST_TIER_PROVIDER"] = "openai"
    os.environ["FAST_TIER_MODEL"] = "gpt-4o-mini"

    config = build_config(
        project_root=project_root,
        clinical_definition_path=project_root / "acute liver failure.txt",
        phenotype="Test",
        dry_run=False,
    )

    if (config.reasoning_tier.provider == "openai" and
        config.reasoning_tier.model == "gpt-4o" and
        config.fast_tier.provider == "openai" and
        config.fast_tier.model == "gpt-4o-mini"):
        print(f"✅ PASSED: Config loaded correctly from environment")
        return True
    else:
        print(f"❌ FAILED: Config not loaded correctly: {config}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("LLM Client Factory Tests")
    print("="*60)

    results = []
    results.append(("Dry-run mode raises error", test_dry_run_mode()))
    results.append(("OpenAI missing key", test_openai_missing_key()))
    results.append(("Azure missing credentials", test_azure_openai_missing_credentials()))
    results.append(("Anthropic missing key", test_anthropic_missing_key()))
    results.append(("Unknown provider raises error", test_unknown_provider()))
    results.append(("OpenAI with valid key", test_openai_with_key()))
    results.append(("Config loading from environment", test_config_loading()))

    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60 + "\n")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())


