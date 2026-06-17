# AWS Lambda Deployment

Argus runs as a Lambda function triggered by EventBridge on a weekly schedule.
Deployment uses [AWS SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html),
which packages and uploads the code automatically — no manual S3 setup needed.

**Prerequisites**

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- AWS credentials configured (`aws configure` or environment variables)
- AWS Resource Explorer enabled with an **aggregator index** in your primary region

    Check if you have one:
    ```bash
    aws resource-explorer-2 get-index --region us-east-1
    ```
    If not, create one:
    ```bash
    aws resource-explorer-2 create-index --type LOCAL --region us-east-1
    aws resource-explorer-2 update-index-type --type AGGREGATOR --region us-east-1
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
| `PrimaryRegion` | No | `us-east-1` | Must match your Resource Explorer aggregator region |
| `IgnoreRegions` | No | _(empty)_ | Comma-separated regions to skip |
| `AiProvider` | No | `bedrock` | `bedrock` \| `anthropic` |
| `AnthropicApiKey` | When `AiProvider=anthropic` | — | Anthropic API key |
| `BedrockModelId` | No | `anthropic.claude-sonnet-4-6` | Bedrock model ID |
| `Schedule` | No | `cron(0 9 ? * MON *)` | EventBridge schedule (default: Mondays 9am UTC) |
| `DryRun` | No | `false` | `true` logs the Slack payload instead of posting |
| `ReportUrlExpiry` | No | `604800` | Pre-signed URL expiry in seconds (default: 7 days) |
| `LambdaMemoryMB` | No | `512` | Increase for large accounts that time out |

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

Note the `HubRoleArn` output — you'll need it for the spoke deployments.

### Spoke accounts (one per target account)

No SAM needed — spoke accounts only get an IAM role:

```bash
aws cloudformation deploy \
  --template-file deploy/aws/multi-account/spoke-role.yaml \
  --stack-name Argus-Spoke \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides HubAccountId=<hub-account-id>
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
