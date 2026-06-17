# Getting Started

Choose your path:

<div class="feature-grid" markdown>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-lightning-bolt:</div>

**[Quick Start (Local)](quickstart.md)**

Run your first scan in 5 minutes using the CLI and Anthropic API. No cloud deployment needed.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-tune:</div>

**[Configuration](configuration.md)**

All environment variables, accounts.yaml reference, and AI provider options.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-magnify-scan:</div>

**[Your First Scan](first-scan.md)**

What to expect from the output and how to interpret findings.
</div>

</div>

## Prerequisites

- Python 3.13+
- Cloud credentials configured for your target cloud:
    - **AWS**: `~/.aws/credentials` default profile, or `AWS_PROFILE` env var. AWS Resource Explorer must be enabled with an **aggregator index** in your primary region.
    - **GCP**: `gcloud auth application-default login`
    - **Azure**: `az login`
- A Slack webhook URL — or set `DRY_RUN=true` to print to stdout instead
- An AI provider (one of):
    - **Anthropic API** (easiest for local dev): set `ANTHROPIC_API_KEY`
    - **AWS Bedrock**: uses your IAM role automatically (AWS only)
    - **Vertex AI**: uses ADC automatically (GCP only)
    - **Azure OpenAI**: uses managed identity automatically (Azure only)

!!! tip "GCP and Azure — deploy first"
    The local CLI currently supports AWS only. For GCP and Azure, deploy the Cloud Run Job or Azure Function (see the [Deployment](../deployment/index.md) section) and run scans from there.
