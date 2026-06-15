# Changelog

## v0.1.0 (2026-06-15)

Initial release.

### Features

- **Multi-cloud support** — AWS, GCP, and Azure adapters with a shared four-method contract (`list_resources`, `get_metrics`, `get_cost`, `get_last_activity`)
- **AI-driven analysis** — ReAct agent loop powered by Claude (Anthropic API, AWS Bedrock, Vertex AI, or Azure OpenAI); no hardcoded idle thresholds
- **AWS adapter** — Resource Explorer for discovery, CloudWatch for metrics (43 resource types + dynamic fallback), Cost Explorer for cost data, CloudTrail for last-activity timestamps
- **GCP adapter** — Cloud Asset Inventory (22 asset types), Cloud Monitoring, BigQuery billing export, Cloud Audit Logs
- **Azure adapter** — Resource Graph (KQL, cross-subscription), Azure Monitor (25 resource types), Cost Management, Activity Log
- **Multi-account AWS** — STS AssumeRole with hub/spoke IAM architecture; one scan covers unlimited accounts
- **Slack delivery** — weekly report with findings ranked by monthly waste, AI-written explanations and recommendations
- **SAM deployment** — `sam build && sam deploy --guided` deploys to AWS Lambda in minutes; no manual S3 setup
- **Docker support** — `docker build --build-arg CLOUD=aws -t argus .` for container-first usage
- **208 tests** — all pass offline with no real cloud credentials required
