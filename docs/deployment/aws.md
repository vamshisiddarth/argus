# AWS Lambda Deployment

Argus runs as a Lambda function triggered by EventBridge Scheduler on a weekly schedule.

## Single account

### One-click deploy

[![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://console.aws.amazon.com/cloudformation/home#/stacks/create/review?templateURL=https://raw.githubusercontent.com/vamshisiddarth/argus/main/deploy/aws/single-account.yaml)

### CLI deploy

```bash
aws cloudformation deploy \
  --template-file deploy/aws/single-account.yaml \
  --stack-name Argus \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      SlackWebhookUrl=https://hooks.slack.com/services/T.../B.../... \
      PrimaryRegion=us-east-1
```

### What gets created

| Resource | Purpose |
|----------|---------|
| Lambda function | Runs the scan weekly |
| EventBridge rule | Triggers Lambda every Monday at 9am UTC |
| IAM execution role | Read-only access to Resource Explorer, CloudWatch, Cost Explorer, CloudTrail, Bedrock |
| Resource Explorer index | Aggregator index for cross-region resource discovery |

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `SlackWebhookUrl` | Yes | — | Slack incoming webhook URL |
| `PrimaryRegion` | No | `us-east-1` | AWS region for the scan |
| `IgnoreRegions` | No | _(empty)_ | Comma-separated regions to skip |
| `AIProvider` | No | `bedrock` | `bedrock` \| `anthropic` |
| `AnthropicApiKey` | When `AIProvider=anthropic` | — | Anthropic API key |
| `Schedule` | No | `cron(0 9 ? * MON *)` | EventBridge schedule expression |
| `ReportS3Bucket` | No | _(empty)_ | S3 bucket for full JSON report |

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

Redeploy with the same stack name — CloudFormation handles the update:

```bash
aws cloudformation deploy \
  --template-file deploy/aws/single-account.yaml \
  --stack-name Argus \
  --capabilities CAPABILITY_IAM
```
