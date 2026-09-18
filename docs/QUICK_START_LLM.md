# Quick Start: Running with LLMs

This document provides step-by-step instructions to run the PhenotypingAgent with real LLM models.

## 5-Minute Setup (OpenAI)

### Step 1: Get API Key
1. Visit https://platform.openai.com/account/api-keys
2. Create a new API key with `gpt-4o` access
3. Copy the key (you'll only see it once)

### Step 2: Create .env File
```bash
cd E:\git\PhenotypingAgent
cp .env.example .env
```

### Step 3: Add Your API Key to .env
Open `.env` in your editor and uncomment/update:
```
OPENAI_API_KEY=sk-your-key-here
REASONING_TIER_PROVIDER=openai
REASONING_TIER_MODEL=gpt-4o
FAST_TIER_PROVIDER=openai
FAST_TIER_MODEL=gpt-4o-mini
```

### Step 4: Test the Setup
```bash
# Install python-dotenv if needed
pip install python-dotenv

# Run a dry-run first (no API calls)
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run true
```

Expected output:
```
Run complete. Report: [.../runs/YYYYMMDD_HHMMSS/report.md]
Final action: done
```

### Step 5: Run with Real LLMs
```bash
# Run with LLMs (limited iterations for cost control)
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --dry-run false \
    --max-iterations 2
```

Expected output:
```
Run complete. Report: [.../runs/YYYYMMDD_HHMMSS/report.md]
Final action: done
```

Check the report:
```bash
cat runs/YYYYMMDD_HHMMSS/report.md
```

## Workflow Execution

When you run the agent, it executes this sequence per iteration:

```
┌─────────────────────────────────────────────────────────────┐
│ START                                                       │
└────────────────────┬────────────────────────────────────────┘
                     ▼
            ┌──────────────────┐
            │  Intake Phase    │ Load clinical definition + database
            └────────┬─────────┘
                     ▼
            ┌──────────────────┐
            │  Survey Phase    │ Discover available concept sets
            └────────┬─────────┘
                     ▼
         ┌───────────────────────────────┐
         │  ITERATION LOOP (default: 8) │
         │  ┌──────────────────────────┐ │
         │  │ Design [LLM-REASONING]   │ │ Select concept sets, refine design
         │  ├──────────────────────────┤ │
         │  │ Write Capr [LLM-REASONING]│ │ Generate/repair Capr code
         │  ├──────────────────────────┤ │
         │  │ Generate [Tools]         │ │ Create cohort in database
         │  ├──────────────────────────┤ │
         │  │ Measure [Tools]          │ │ Run cohort metrics
         │  ├──────────────────────────┤ │
         │  │ Assess [LLM-REASONING]   │ │ Evaluate if ready for validation
         │  ├──────────────────────────┤ │
         │  │ IF ready:                │ │
         │  │ ├─ Evaluate [Tools]      │ │ Validate PPV/sensitivity
         │  │ ├─ Sample Profiles [LLM] │ │ Diagnose FP/FN/TP
         │  │ └─ If good: EXIT         │ │
         │  └──────────────────────────┘ │
         └───────────────┬────────────────┘
                         ▼
            ┌──────────────────┐
            │  Report Phase    │ Generate final report + Capr JSON
            └────────┬─────────┘
                     ▼
         ┌───────────────────────────────┐
         │  OUTPUT                       │
         │  - report.md                  │
         │  - final_cohort.json          │
         │  - ledger.json                │
         └───────────────────────────────┘
```

## Environment Variables Reference

| Variable | Required | Example | Purpose |
|----------|----------|---------|---------|
| `REASONING_TIER_PROVIDER` | Yes | `openai` | LLM provider for reasoning tier |
| `REASONING_TIER_MODEL` | Yes | `gpt-4o` | Model name for reasoning |
| `FAST_TIER_PROVIDER` | Yes | `openai` | LLM provider for fast tier |
| `FAST_TIER_MODEL` | Yes | `gpt-4o-mini` | Model name for fast tier |
| `OPENAI_API_KEY` | If `openai` | `sk-...` | OpenAI API key |
| `AZURE_OPENAI_API_KEY` | If `azure_openai` | `...` | Azure API key |
| `AZURE_OPENAI_ENDPOINT` | If `azure_openai` | `https://...` | Azure endpoint URL |
| `ANTHROPIC_API_KEY` | If `anthropic` | `sk-ant-...` | Anthropic API key |
| `BEDROCK_AWS_REGION` | If `bedrock` | `us-east-1` | AWS region for Bedrock |
| `BEDROCK_AWS_PROFILE` | Optional for `bedrock` | `default` | Named AWS profile override |

## CLI Arguments Reference

```bash
phenotyping-agent run [OPTIONS]

Options:
  --clinical-definition TEXT              Path to clinical definition file [required]
  --phenotype TEXT                        Optional phenotype name override
  --dry-run BOOLEAN                       Use dry-run fixtures (default: false)
  --max-iterations INTEGER                Cap on design iterations (default: 8)
  --run-id TEXT                           Run folder identifier
  --reasoning-tier-provider TEXT          openai|azure_openai|anthropic|bedrock
  --reasoning-tier-model TEXT             Model name (e.g., gpt-4o)
  --fast-tier-provider TEXT               openai|azure_openai|anthropic|bedrock
  --fast-tier-model TEXT                  Model name (e.g., gpt-4o-mini)
  --help                                  Show help message
```

## Example Commands

### OpenAI (recommended)
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --max-iterations 3
```

### Azure OpenAI
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --max-iterations 3 \
    --reasoning-tier-provider azure_openai \
    --reasoning-tier-model gpt-4o-deployment \
    --fast-tier-provider azure_openai \
    --fast-tier-model gpt-4o-mini-deployment
```

### Anthropic Claude
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --max-iterations 3 \
    --reasoning-tier-provider anthropic \
    --reasoning-tier-model claude-3-5-sonnet-20241022 \
    --fast-tier-provider anthropic \
    --fast-tier-model claude-3-5-haiku-20241022
```

### Amazon Bedrock + Claude Opus
```bash
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --max-iterations 3 \
    --reasoning-tier-provider bedrock \
    --reasoning-tier-model anthropic.claude-3-opus-20240229-v1:0 \
    --fast-tier-provider bedrock \
    --fast-tier-model anthropic.claude-3-haiku-20240307-v1:0
```

### Hybrid (CLI args override .env)
```bash
# Use OpenAI for reasoning, Anthropic for fast
phenotyping-agent run \
    --clinical-definition "acute liver failure.txt" \
    --reasoning-tier-provider openai \
    --reasoning-tier-model gpt-4o \
    --fast-tier-provider anthropic \
    --fast-tier-model claude-3-5-haiku-20241022
```

## Monitoring Costs

After each run, check:

1. **OpenAI Dashboard:** https://platform.openai.com/account/usage/overview
2. **Azure Portal:** Cognitive Services > Your resource > Cost Management
3. **Anthropic Console:** https://console.anthropic.com/usage
4. **AWS Billing + Bedrock usage metrics:** AWS Console

For a typical ALF run (5 iterations):
- **OpenAI:** $0.50 - $1.00
- **Anthropic:** $0.30 - $0.60
- **Amazon Bedrock:** depends on region and selected Claude model
- **Azure:** Depends on reserved capacity

## Troubleshooting

### "ImportError: No module named 'dotenv'"
```bash
pip install python-dotenv
```

### "ValueError: LLM provider is set to 'none'"
**Cause:** .env not loaded or models not configured
**Solution:** 
1. Verify .env exists: `ls .env`
2. Check REASONING_TIER_PROVIDER: `grep REASONING .env`
3. Pass CLI args: `--reasoning-tier-provider openai --reasoning-tier-model gpt-4o`

### "OPENAI_API_KEY environment variable not set"
**Cause:** API key missing from .env
**Solution:**
```bash
echo "OPENAI_API_KEY=sk-your-key" >> .env
```

### "Rate limit exceeded"
**Cause:** Too many API calls in short time
**Solution:**
- Wait 1 minute before retrying
- Use `--max-iterations 1` for testing
- Check provider dashboard for quota

### Report shows deterministic output
**Cause:** Dry-run mode is still active or LLM not initialized
**Solution:**
```bash
# Make sure --dry-run false is set
phenotyping-agent run ... --dry-run false
# Check .env for correct provider/model
cat .env | grep REASONING_TIER
```

## Next Steps

1. ✅ Set up .env file with your API keys
2. ✅ Test with `--dry-run true` first
3. ✅ Run with `--max-iterations 2` for budget control
4. ✅ Review `runs/*/report.md` for results
5. ✅ Increase iterations as needed for production

For detailed configuration options, see: [docs/LLM_CONFIGURATION.md](LLM_CONFIGURATION.md)


