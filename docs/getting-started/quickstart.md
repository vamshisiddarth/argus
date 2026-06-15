# Quick Start (Local)

Scan your AWS account from your laptop in under 5 minutes.

## :material-source-repository: 1. Clone and install

```bash
git clone https://github.com/vamshisiddarth/argus.git
cd argus
make setup
```

Or manually (install only what you need):

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements/aws.txt   # or gcp.txt / azure.txt
```

## :material-tune: 2. Configure

```bash
cp .env.example .env
```

Open `.env` and set the minimum required values:

```ini title=".env"
# AI provider — Anthropic is the easiest for local dev
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...        # get from console.anthropic.com

# AWS region where your Resource Explorer aggregator index lives
PRIMARY_REGION=us-east-1
RESOURCE_EXPLORER_REGION=us-east-1

# Set to true to print the Slack payload instead of posting it
DRY_RUN=true
```

!!! info "Resource Explorer aggregator index"
    Argus uses AWS Resource Explorer to discover all resources.
    You need an **aggregator index** in `PRIMARY_REGION`.

    Check if you have one:
    ```bash
    aws resource-explorer-2 get-index --region us-east-1
    ```

    If not, create one:
    ```bash
    # Create a local index first
    aws resource-explorer-2 create-index --type LOCAL --region us-east-1

    # Promote it to aggregator
    aws resource-explorer-2 update-index-type --type AGGREGATOR --region us-east-1
    ```

## :material-play-circle-outline: 3. Run your first scan

```bash
python main.py --cloud aws --run-now --dry-run
```

The agent will:

1. Discover all billable resources via Resource Explorer
2. Investigate candidates — calling CloudWatch, Cost Explorer, and CloudTrail
3. Print the Slack payload to stdout (because `DRY_RUN=true`)

Typical output:

```
INFO  scan_start cloud=aws ignore_regions=[] primary_region=us-east-1 mode=single
INFO  agent_iteration iteration=1
INFO  tool_executed tool=list_resources is_error=False
INFO  agent_iteration iteration=2
INFO  tool_executed tool=get_cost is_error=False
...
INFO  agent_complete findings_count=4
INFO  scan_complete findings=4 total_waste_usd=42.65
```

## :material-slack: 4. Post to Slack

Once you're happy with the output, set your webhook URL and remove `--dry-run`:

```ini title=".env"
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
DRY_RUN=false
```

```bash
python main.py --cloud aws --run-now
```

## :material-console: CLI reference

```
python main.py --cloud aws --run-now [options]

Options:
  --dry-run                  Print Slack payload instead of posting
  --ignore-regions REGIONS   Comma-separated regions to skip
                             e.g. --ignore-regions ap-east-1,me-south-1
  --ai-provider PROVIDER     anthropic | bedrock (default: anthropic)
  --accounts PATH            Path to accounts.yaml for multi-account mode
  --primary-region REGION    AWS region for boto3 session (default: us-east-1)
```

## :material-arrow-right-circle-outline: Next steps

- [Configure all options](configuration.md)
- [Understand the findings](first-scan.md)
- [Deploy to AWS Lambda](../deployment/aws.md) for weekly automated scans
