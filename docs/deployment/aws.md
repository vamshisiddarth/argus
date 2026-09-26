# AWS Lambda Deployment

Argus runs as a Lambda function triggered by EventBridge on a weekly schedule.
Deployment uses [AWS SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html),
which packages and uploads the code automatically — no manual S3 setup needed.

**Prerequisites**

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- AWS credentials configured (`aws configure` or environment variables)
- AWS Resource Explorer enabled with an **aggregator index** in `us-east-1`. The Lambda reads the aggregator region from `RESOURCE_EXPLORER_REGION`, which the template doesn't set, so it defaults to `us-east-1`. If your aggregator is elsewhere, add `RESOURCE_EXPLORER_REGION` to the function's environment after deploying.

    Check if you have one:
    ```bash
    aws resource-explorer-2 get-index --region us-east-1
    ```
    If not, create one (plus a default view, which Argus's search relies on):
    ```bash
    aws resource-explorer-2 create-index --region us-east-1
    INDEX_ARN=$(aws resource-explorer-2 get-index --region us-east-1 --query Arn --output text)
    aws resource-explorer-2 update-index-type --arn "$INDEX_ARN" --type AGGREGATOR --region us-east-1

    # Search uses the region's default view; include tags so Argus sees them
    VIEW_ARN=$(aws resource-explorer-2 create-view --view-name argus-all \
      --included-properties Name=tags --region us-east-1 --query View.ViewArn --output text)
    aws resource-explorer-2 associate-default-view --view-arn "$VIEW_ARN" --region us-east-1
    ```

!!! tip "Cost Explorer activation (recommended)"
    For accurate per-resource cost data, enable two things in AWS Console → **Cost Management → Settings**:

    1. **Cost Explorer** — first activation takes up to 24 hours
    2. **Resource-level data** — enables `GetCostAndUsageWithResources`

    Without this, cost fields show `$0.00`. Argus still finds idle resources via metrics and activity signals, but cost-based sorting and estimates will be unavailable.

---

## Single account

```bash
cd deploy/aws/single-account
sam build
sam deploy --guided
```

`sam deploy --guided` prompts for all parameters and saves them to `samconfig.toml`.
Subsequent deploys are just `sam deploy`.

Or use the Makefile shortcut from the repo root:

```bash
make deploy-aws
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `SlackWebhookUrl` | Yes | — | Slack incoming webhook URL |
| `PrimaryRegion` | No | `us-east-1` | Region for the boto3 session. Does not change the Resource Explorer aggregator region (see Prerequisites) |
| `IgnoreRegions` | No | _(empty)_ | Comma-separated regions to skip |
| `AiProvider` | No | `bedrock` | `bedrock` \| `anthropic` |
| `AnthropicApiKey` | When `AiProvider=anthropic` | — | Anthropic API key |
| `BedrockModelId` | No | `anthropic.claude-sonnet-4-6` | Bedrock model ID |
| `BedrockRegion` | No | `us-east-1` | Region where Bedrock model access is enabled |
| `Schedule` | No | `cron(0 9 ? * MON *)` | EventBridge schedule (default: Mondays 9am UTC) |
| `DryRun` | No | `false` | `true` logs a payload preview instead of posting; no Jira calls |
| `LambdaMemoryMB` | No | `512` | `256` / `512` / `1024` / `2048`. Increase for large accounts |
| `LambdaTimeoutSeconds` | No | `900` | Lambda timeout (15 minutes max) |

The report link's expiry (`REPORT_URL_EXPIRY`, default 7 days) and remediation settings (`REMEDIATION_ENABLED`, `JIRA_*`) aren't template parameters. Add them to the function's environment variables if you need them.

### What gets created

| Resource | Purpose |
|----------|---------|
| Lambda function | Runs the scan on schedule |
| EventBridge rule | Triggers Lambda every Monday at 9am UTC |
| IAM execution role | Read-only access to Resource Explorer, CloudWatch, Cost Explorer, CloudTrail, Bedrock |
| S3 bucket | Created automatically as `argus-reports-{accountId}-{region}`. Stores full JSON + HTML reports per scan (90-day retention). `REPORT_S3_BUCKET` is wired into the Lambda environment automatically — no manual bucket creation needed. The Slack digest links to the HTML report via a 7-day pre-signed URL. |

---

## Multi-account

### Hub account (runs Argus)

```bash
cd deploy/aws/multi-account/hub
sam build
sam deploy --guided
```

Or:

```bash
make deploy-aws-multi
```

Note the `HubRoleArn` output — you'll need it for the spoke deployments. The hub template also takes `AccountsConfig` (JSON list of accounts) and `SpokeRoleName` (default `ArgusSpokeRole`).

### Spoke accounts (one per target account)

No SAM needed — spoke accounts only get an IAM role:

```bash
aws cloudformation deploy \
  --template-file deploy/aws/multi-account/spoke-role.yaml \
  --stack-name Argus-Spoke \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides HubRoleArn=<HubRoleArn output from the hub stack>
```

The spoke role is read-only and only trusts the hub Lambda role to assume it.

---

## Triggering a manual scan

```bash
aws lambda invoke \
  --function-name Argus \
  --payload '{}' \
  output.json && cat output.json
```

## Viewing logs

```bash
aws logs tail /aws/lambda/Argus --follow
```

## Updating

```bash
cd deploy/aws/single-account
sam build && sam deploy
```

SAM detects what changed and shows a changeset before applying.
