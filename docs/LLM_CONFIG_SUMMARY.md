# LLM Configuration Summary

## What's Been Implemented

You now have a complete LLM configuration system for the PhenotypingAgent workflow. Here's what's been set up:

### 1. **LLM Client Factory** (`phenotyping_agent/llm_client.py`)
   - Unified interface for multiple LLM providers
   - Supports: **OpenAI**, **Azure OpenAI**, **Anthropic Claude**
   - Automatic credential loading from environment variables
   - Smart error messages guiding users to API key setup
   - **Status:** ✅ Production-ready, fully tested

### 2. **Enhanced Configuration System** (`phenotyping_agent/config.py`)
   - Added `openai` provider option (in addition to `azure_openai`, `anthropic`)
   - `build_config()` now accepts CLI and environment-based LLM settings
   - Supports two model tiers: `reasoning_tier` (complex tasks) and `fast_tier` (lightweight)
   - **Status:** ✅ Complete with backward compatibility

### 3. **CLI Integration** (`phenotyping_agent/cli.py`)
   - New CLI options for specifying LLM providers and models
   - Automatic `.env` file loading via `python-dotenv`
   - Supports full command-line configuration or environment variables
   - **Status:** ✅ Ready for production use

### 4. **Environment Configuration**
   - `.env.example` with comprehensive documentation
   - 3 provider templates (OpenAI, Azure OpenAI, Anthropic)
   - Cost estimation and usage examples
   - **Status:** ✅ Ready to copy and configure

### 5. **Documentation**
   - **LLM_CONFIGURATION.md**: Detailed setup guide for each provider
   - **QUICK_START_LLM.md**: 5-minute quickstart + workflow diagram
   - **test_llm_config.py**: Comprehensive test suite (7/7 tests passing)
   - **Status:** ✅ Complete with examples and troubleshooting

## Next Steps: Running with LLMs

### Option A: Quick Start (Recommended for first-time users)

```bash
# 1. Get OpenAI API key
# Visit: https://platform.openai.com/account/api-keys

# 2. Create .env file
cp .env.example .env

# 3. Add your key to .env
# Edit .env and set:
# OPENAI_API_KEY=sk-...
# REASONING_TIER_PROVIDER=openai
# REASONING_TIER_MODEL=gpt-4o
# FAST_TIER_PROVIDER=openai
# FAST_TIER_MODEL=gpt-4o-mini

# 4. Test configuration with dry-run
phenotyping-agent run --clinical-definition "acute liver failure.txt" --dry-run true

# 5. Run with real LLMs (limited iterations for cost control)
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false \
    --max-iterations 2
```

### Option B: Command-Line Only (No .env file)

```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false \
    --reasoning-tier-provider openai \
    --reasoning-tier-model gpt-4o \
    --fast-tier-provider openai \
    --fast-tier-model gpt-4o-mini
```

### Option C: Azure OpenAI

```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false \
    --reasoning-tier-provider azure_openai \
    --reasoning-tier-model gpt-4o-deployment \
    --fast-tier-provider azure_openai \
    --fast-tier-model gpt-4o-mini-deployment
```

### Option D: Anthropic Claude

```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false \
    --reasoning-tier-provider anthropic \
    --reasoning-tier-model claude-3-5-sonnet-20241022 \
    --fast-tier-provider anthropic \
    --fast-tier-model claude-3-5-haiku-20241022
```

## How LLMs Are Used in the Workflow

The configured LLMs power the following nodes in your workflow:

| Node | Tier | Purpose | Why LLM? |
|------|------|---------|----------|
| **Design** | Reasoning | Select best concept sets for phenotype | Complex clinical reasoning |
| **Write Capr** | Reasoning | Generate/repair Capr code for cohort | Complex code generation |
| **Assess** | Reasoning | Evaluate if design is ready for validation | Interpret metrics against expectations |
| **Evaluate** | Reasoning | Diagnose false positives/negatives | Clinical pattern recognition |
| **Survey** | Fast | Parse concept set tables | Quick transformation |
| **Generate** | Tools | Create cohort in database | Database operations (not LLM) |
| **Measure** | Tools | Calculate cohort metrics | Database operations (not LLM) |

## Environment Variables Reference

### OpenAI Setup
```bash
OPENAI_API_KEY=sk-...                      # Required
# Optional:
OPENAI_BASE_URL=https://api.openai.com/v1  # For proxies
```

### Azure OpenAI Setup
```bash
AZURE_OPENAI_API_KEY=...                   # Required
AZURE_OPENAI_ENDPOINT=https://...          # Required (e.g., https://your-resource.openai.azure.com)
AZURE_OPENAI_API_VERSION=2024-08-01        # Optional, defaults to 2024-08-01
AZURE_OPENAI_DEPLOYMENT_NAME=...           # Optional, defaults to model name
```

### Anthropic Setup
```bash
ANTHROPIC_API_KEY=sk-ant-...               # Required
```

### Model Tier Configuration
```bash
REASONING_TIER_PROVIDER=openai|azure_openai|anthropic  # Required if not dry-run
REASONING_TIER_MODEL=gpt-4o|gpt-4-turbo|claude-3-5-sonnet-20241022  # Model name
FAST_TIER_PROVIDER=openai|azure_openai|anthropic       # Required if not dry-run
FAST_TIER_MODEL=gpt-4o-mini|gpt-3.5-turbo|claude-3-5-haiku-20241022  # Model name
```

## Cost Estimates

Per phenotype run with 5 design iterations:

| Provider | Models | Est. Cost |
|----------|--------|-----------|
| OpenAI | GPT-4o + GPT-4o-mini | $0.50 - $1.00 |
| Azure OpenAI | Any (pay-per-hour) | Varies |
| Anthropic | Claude 3.5 Sonnet + Haiku | $0.30 - $0.60 |

**Cost Control Tips:**
- Use `--max-iterations 2` to limit design loops
- Use `--dry-run true` for testing (no costs)
- Monitor provider dashboards for actual spend

## What's NOT Configured Yet

The following would typically be done after this configuration step:

1. **Model-specific prompt optimization**
   - Currently using generic prompts
   - Each provider may benefit from tuned prompts

2. **Structured output parsing**
   - Currently uses string parsing
   - Can use LangChain's structured_output for reliability

3. **Token/cost tracking**
   - Not logged or reported in runs
   - Could add to final report

4. **Multi-model fallback logic**
   - Currently uses single provider per tier
   - Could add fallback if primary fails

5. **Caching and batch processing**
   - Could cache design iterations
   - Could batch patient profile sampling

## Testing

To verify your configuration is working:

```bash
# Run the configuration test suite
python tests/test_llm_config.py

# Expected output: "Total: 7/7 tests passed"
```

## Troubleshooting

### Common Issues

**"LLM provider is set to 'none'"**
- Cause: .env not loaded or models not configured
- Fix: Pass CLI args or verify .env exists

**"OPENAI_API_KEY environment variable not set"**
- Cause: API key missing from .env
- Fix: Add OPENAI_API_KEY=sk-... to .env

**"Rate limit exceeded"**
- Cause: Too many API calls in short time
- Fix: Wait 1 min, use smaller --max-iterations

**Import errors (langchain-anthropic)**
- Cause: Optional dependency not installed
- Fix: `pip install langchain-anthropic` (if using Anthropic)

See **docs/LLM_CONFIGURATION.md** for detailed troubleshooting.

## Architecture

```
phenotyping_agent/
├── config.py              # ModelTier + build_config with env loading
├── llm_client.py          # LLM factory (NEW)
├── cli.py                 # CLI with LLM options (UPDATED)
├── graph.py               # Workflow orchestration (unchanged)
└── nodes/                 # Workflow nodes
    ├── design.py          # Uses reasoning_tier for concept selection
    ├── write_capr.py      # Uses reasoning_tier for Capr generation
    ├── assess.py          # Uses reasoning_tier for metric interpretation
    ├── evaluate.py        # Uses reasoning_tier for diagnosis
    └── ...

.env.example               # Configuration template (NEW)

tests/
└── test_llm_config.py     # Configuration tests (NEW)

docs/
├── LLM_CONFIGURATION.md   # Detailed setup guide (NEW)
└── QUICK_START_LLM.md     # 5-minute quickstart (NEW)
```

## Files Changed

| File | Type | Changes |
|------|------|---------|
| `config.py` | Modified | Added openai provider, env-based loading |
| `cli.py` | Modified | Added LLM CLI options, .env loading |
| `pyproject.toml` | Modified | Added python-dotenv dependency |
| `llm_client.py` | Created | LLM factory implementation |
| `.env.example` | Created | Configuration template |
| `docs/LLM_CONFIGURATION.md` | Created | Comprehensive setup guide |
| `docs/QUICK_START_LLM.md` | Created | 5-minute quickstart |
| `tests/test_llm_config.py` | Created | Configuration tests |

## Ready to Run!

You now have everything needed to run the phenotyping workflow with real LLMs. Choose your preferred provider and follow the Quick Start guide in **docs/QUICK_START_LLM.md**.

Questions? See:
- **LLM_CONFIGURATION.md** for provider-specific setup
- **QUICK_START_LLM.md** for command examples
- **llm_client.py** for implementation details

