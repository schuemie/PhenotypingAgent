# LLM Configuration Guide

This guide explains how to configure and run the PhenotypingAgent with real LLM models.

## Overview

The PhenotypingAgent uses two LLM tiers for different purposes:

1. **Reasoning Tier** (`reasoning_tier`): High-quality models for complex reasoning tasks
   - Design iteration and refinement
   - Capr code generation and repair
   - Patient profile interpretation
   - Expectation evaluation and diagnosis
   - Models: GPT-4o, GPT-4-turbo, Claude 3.5 Sonnet, Claude 3 Opus

2. **Fast Tier** (`fast_tier`): Efficient models for lightweight expansions
   - Concept set retrieval and selection
   - Quick validation checks
   - Deterministic transformations
   - Models: GPT-4o-mini, GPT-3.5-turbo, Claude 3.5 Haiku

## Supported LLM Providers

### 1. OpenAI (Recommended for most users)

**Prerequisites:**
- OpenAI API account: https://platform.openai.com/account/api-keys
- API key with GPT-4o access

**Setup:**
```bash
# Copy .env.example to .env
cp .env.example .env

# Edit .env and set:
OPENAI_API_KEY=sk-...
REASONING_TIER_PROVIDER=openai
REASONING_TIER_MODEL=gpt-4o
FAST_TIER_PROVIDER=openai
FAST_TIER_MODEL=gpt-4o-mini
```

**Run:**
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false
```

### 2. Azure OpenAI (For enterprise users with Azure subscriptions)

**Prerequisites:**
- Azure OpenAI deployment
- Resource and deployment names
- API key from Azure Portal

**Setup:**
```bash
# Edit .env and set:
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-08-01
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o-deployment
REASONING_TIER_PROVIDER=azure_openai
REASONING_TIER_MODEL=gpt-4o-deployment
FAST_TIER_PROVIDER=azure_openai
FAST_TIER_MODEL=gpt-4o-mini-deployment
```

**Run:**
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false
```

### 3. Anthropic Claude (For Claude-preferred workflows)

**Prerequisites:**
- Anthropic console account: https://console.anthropic.com/account/keys
- API key with sufficient quota

**Setup:**
```bash
# Edit .env and set:
ANTHROPIC_API_KEY=sk-ant-...
REASONING_TIER_PROVIDER=anthropic
REASONING_TIER_MODEL=claude-3-5-sonnet-20241022
FAST_TIER_PROVIDER=anthropic
FAST_TIER_MODEL=claude-3-5-haiku-20241022
```

**Run:**
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false
```

### 4. Bedrock with Anthropic Claude

Two Bedrock connection modes are supported. The model tier configuration is the same for both;
the presence of `BEDROCK_API_KEY` or `BEDROCK_BASE_URL` selects the custom gateway.

#### Standard AWS Bedrock

**Prerequisites:**
- AWS account with Amazon Bedrock model access enabled
- Access to the Anthropic Claude model IDs you want to use
- AWS credentials available via profile, SSO, environment variables, or workload role
- Region configured for Bedrock (for example `us-east-1`)

**Install the optional dependency:**
```bash
pip install -e ".[bedrock]"
```

**Setup:**
```bash
# Edit .env and set:
BEDROCK_AWS_REGION=us-east-1
REASONING_TIER_PROVIDER=bedrock
REASONING_TIER_MODEL=anthropic.claude-3-opus-20240229-v1:0
FAST_TIER_PROVIDER=bedrock
FAST_TIER_MODEL=anthropic.claude-3-haiku-20240307-v1:0

# Optional if you use a named AWS profile:
BEDROCK_AWS_PROFILE=default
```

**Run:**
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false
```

#### J&J Bedrock gateway

The J&J gateway uses an API key rather than AWS credentials. It sends non-streaming Anthropic
Bedrock payloads to `/model/{URL-encoded model ID}/invoke`, matching `EllmerJnj.R`. Standard AWS
region, profile, and credentials are not required in this mode, nor is the optional
`langchain-aws` package.

**Setup:**
```bash
# Edit .env and set:
BEDROCK_API_KEY=...
# Optional; this is the default when BEDROCK_API_KEY is present:
BEDROCK_BASE_URL=https://genaiapigwna.jnj.com
# Optional; defaults to bedrock-2023-05-31:
BEDROCK_ANTHROPIC_VERSION=bedrock-2023-05-31

REASONING_TIER_PROVIDER=bedrock
REASONING_TIER_MODEL=us.anthropic.claude-sonnet-4-20250514-v1:0
FAST_TIER_PROVIDER=bedrock
FAST_TIER_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
```

The API key is sent only in the `x-api-key` request header and is excluded from model metadata and
LLM event logs. Do not commit it to source control.

## Configuration Methods

### Method 1: Environment File (.env) - Recommended

1. Copy the template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your credentials and model choices

3. Run (environment variables are loaded automatically):
   ```bash
   phenotyping-agent run --clinical-definition "acute liver failure.txt" --dry-run false
   ```

### Method 2: Command-Line Arguments

Pass LLM configuration directly via CLI options:

```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false \
    --reasoning-tier-provider openai \
    --reasoning-tier-model gpt-4o \
     --fast-tier-provider openai \
    --fast-tier-model gpt-4o-mini
```

### Method 3: Environment Variables (Advanced)

Set variables directly in your shell:

```bash
export REASONING_TIER_PROVIDER=openai
export REASONING_TIER_MODEL=gpt-4o
export FAST_TIER_PROVIDER=openai
export FAST_TIER_MODEL=gpt-4o-mini
export OPENAI_API_KEY=sk-...

phenotyping-agent run --clinical-definition "acute liver failure.txt" --dry-run false
```

## Dry-Run Mode (Testing without LLM costs)

To test the workflow without consuming LLM tokens:

```bash
# Uses fixture-backed models (no API keys required)
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run true
```

This is useful for:
- Validating clinical definitions
- Testing workflow integration
- Debugging without incurring costs

## Cost Estimation

Typical costs per phenotype run (ALF example, 5 iterations):

| Provider | Reasoning Tier | Fast Tier | Total |
|----------|---|---|---|
| OpenAI (GPT-4o + GPT-4o-mini) | $0.50 | $0.05 | ~$0.55 |
| Azure OpenAI | Pay-per-hour (reserved capacity) | - | Varies |
| Anthropic (Claude 3.5 Sonnet + Haiku) | $0.30 | $0.02 | ~$0.32 |
| Amazon Bedrock (Claude Opus + Haiku) | Region/model dependent | Region/model dependent | Varies |

**Cost control options:**
- Use `--max-iterations 2` to limit design loops
- Use fast-tier models for reasoning if budget-constrained
- Enable `dry_run=true` for testing before production runs

## Troubleshooting

### "LLM provider is set to 'none'"
**Cause:** Config not loaded or models not configured
**Solution:** 
```bash
# Verify .env exists and is loaded
ls -la .env
# Or pass CLI arguments
phenotyping-agent run ... --reasoning-tier-provider openai --reasoning-tier-model gpt-4o
```

### "OPENAI_API_KEY environment variable not set"
**Cause:** Missing API key
**Solution:**
```bash
# Check if .env is being loaded
cat .env | grep OPENAI_API_KEY
# If missing, add it to .env
echo "OPENAI_API_KEY=sk-..." >> .env
```

### "Deployment name not found" (Azure)
**Cause:** Wrong deployment name in config
**Solution:**
```bash
# List available deployments
az cognitiveservices account deployment list --resource-group <rg> --name <resource>
# Update AZURE_OPENAI_DEPLOYMENT_NAME in .env
```

### "Amazon Bedrock region not configured"
**Cause:** No AWS region is set for Bedrock requests
**Solution:**
```bash
export BEDROCK_AWS_REGION=us-east-1
# or use AWS_REGION / AWS_DEFAULT_REGION
```

If you intended to use the J&J gateway instead, set `BEDROCK_API_KEY`; no AWS region is needed.

### "BEDROCK_API_KEY must be set" (custom Bedrock gateway)
**Cause:** `BEDROCK_BASE_URL` selects custom gateway mode, but no gateway API key is configured
**Solution:** Set `BEDROCK_API_KEY` in `.env` or remove `BEDROCK_BASE_URL` to use standard AWS
Bedrock authentication.

### "AccessDeniedException" or model access errors (Bedrock)
**Cause:** The AWS principal does not have Bedrock permissions, or the Claude model is not enabled in that region
**Solution:**
- Verify Bedrock model access is granted in the AWS console
- Confirm the selected model ID exists in your region
- Ensure the AWS profile/role has Bedrock invoke permissions

### "Rate limit exceeded"
**Cause:** Too many concurrent calls or quota exhausted
**Solution:**
- Reduce `--max-iterations` to limit calls
- Use `--fast-tier-model` with smaller budget
- Wait before retrying (typically 1 min)
- Contact provider to increase quota

## Best Practices

1. **Security:**
   - Never commit `.env` file with real API keys
   - Use `.gitignore` to exclude `.env`
   - Rotate API keys regularly

2. **Cost Control:**
   - Start with `--dry-run true` for testing
   - Use `--max-iterations 2` for initial runs
   - Monitor actual costs in provider dashboards

3. **Model Selection:**
   - Use reasoning tier only for complex tasks (design, diagnosis)
   - Use fast tier for all lightweight operations
   - Consider cheaper models if fine-tuning batch processing
    - For Bedrock Claude, use full Bedrock model IDs such as `anthropic.claude-3-opus-20240229-v1:0`

4. **Error Recovery:**
   - Runs support checkpoint/resume
   - Failed runs can be resumed without full restart
   - Check `runs/{run_id}/` for intermediate artifacts

## Model Recommendations

### For Clinical Phenotyping
**Best:** GPT-4o (reasoning) + GPT-4o-mini (fast)
- Strong causal reasoning
- Good code generation
- Well-tested on biomedical tasks

### For Cost-Sensitive Deployments
**Alternative:** Claude 3.5 Sonnet + Haiku
- Excellent reasoning for lower cost
- Strong at code generation
- Good for complex design workflows

### For Enterprise/Compliance
**Required:** Azure OpenAI
- Data residency in Azure
- Compliance with enterprise policies
- Pay-per-hour reserved capacity

### For AWS-Native Deployments
**Recommended:** Amazon Bedrock + Anthropic Claude
- Uses standard AWS credential and region configuration
- Fits environments that already govern AI access through AWS
- Lets you stay within Bedrock-managed model access and billing

## Next Steps

1. Create `.env` file with your credentials
2. Run a dry-run first to validate configuration:
   ```bash
   phenotyping-agent run --clinical-definition "acute liver failure.txt" --dry-run true
   ```
3. Run with real LLMs on small iteration budget:
   ```bash
   phenotyping-agent run \
       --clinical-definition "acute liver failure.txt" \
       --dry-run false \
       --max-iterations 2
   ```
4. Monitor costs and performance, adjust models/budget as needed

## Support

For issues with LLM configuration:
1. Check error message and provider status page
2. Verify API key and permissions
3. Test with simpler clinical definition first
4. Review `.env` file format and environment loading
