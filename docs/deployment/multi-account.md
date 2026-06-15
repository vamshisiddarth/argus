# Multi-Account (AWS)

Argus can scan multiple AWS accounts in a single weekly run using STS AssumeRole.

## Architecture

```
Hub Account (runs Argus Lambda)
│
├── assumes role → Account A (dev)   → scans, returns findings
├── assumes role → Account B (staging) → scans, returns findings
└── assumes role → Account C (prod)  → scans, returns findings
                                               │
                                    Single Slack report with all findings
```

## Setup

### 1. Deploy the hub (once)

```bash
aws cloudformation deploy \
  --template-file deploy/aws/multi-account/hub.yaml \
  --stack-name Argus-Hub \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      SlackWebhookUrl=https://hooks.slack.com/services/... \
      PrimaryRegion=us-east-1
```

Note the **Lambda execution role ARN** from the stack outputs — you'll need it for the spoke roles.

### 2. Deploy spoke roles (once per target account)

Run this in **each account** you want to scan:

```bash
aws cloudformation deploy \
  --template-file deploy/aws/multi-account/spoke-role.yaml \
  --stack-name Argus-Spoke \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      HubAccountId=<hub-account-id>
```

This creates a read-only `ArgusSpokeRole` that the hub Lambda can assume.

### 3. Configure accounts

Set `ACCOUNTS_MODE=multi` and `ACCOUNTS_CONFIG` in the Lambda environment:

```json
[
  {"id": "111122223333", "name": "dev",     "role_arn": "arn:aws:iam::111122223333:role/ArgusSpokeRole"},
  {"id": "444455556666", "name": "staging", "role_arn": "arn:aws:iam::444455556666:role/ArgusSpokeRole"},
  {"id": "999900001111", "name": "prod",    "role_arn": "arn:aws:iam::999900001111:role/ArgusSpokeRole"}
]
```

Or use `accounts.yaml` with the CLI:

```yaml title="accounts.yaml"
mode: multi

accounts:
  - id: "111122223333"
    name: dev
    role_arn: arn:aws:iam::111122223333:role/ArgusSpokeRole
  - id: "444455556666"
    name: staging
    role_arn: arn:aws:iam::444455556666:role/ArgusSpokeRole
  - id: "999900001111"
    name: prod
    role_arn: arn:aws:iam::999900001111:role/ArgusSpokeRole
```

```bash
python main.py --cloud aws --run-now --accounts accounts.yaml
```

## How it works

1. The hub Lambda reads `ACCOUNTS_CONFIG`
2. For each account, it calls `sts:AssumeRole` to get temporary credentials (1-hour TTL)
3. It creates a separate `AWSAdapter` per account and runs the agent loop
4. All findings are merged into one report and delivered to Slack as a single message
5. The Slack report labels each finding with the account name

## Security

- Spoke roles are **read-only** — no write permissions
- Temporary credentials expire after 1 hour — never stored
- The hub Lambda role only needs `sts:AssumeRole` in addition to its own account's read permissions
- You control exactly which accounts to include via `ACCOUNTS_CONFIG`

!!! tip "AWS Organizations"
    If you use AWS Organizations, you can automate spoke role deployment using a CloudFormation
    StackSet — deploy `spoke-role.yaml` across all member accounts in one step.
