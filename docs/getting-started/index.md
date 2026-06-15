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
    - **AWS**: `~/.aws/credentials` default profile, or `AWS_PROFILE` env var
    - **GCP**: `gcloud auth application-default login`
    - **Azure**: `az login`
- A Slack webhook URL — or set `DRY_RUN=true` to print to stdout instead
- An AI provider:
    - **Anthropic API** (easiest for local dev): set `ANTHROPIC_API_KEY`
    - **AWS Bedrock**: uses your IAM role automatically
    - **Vertex AI**: uses ADC automatically
    - **Azure OpenAI**: uses managed identity automatically
