# Troubleshooting

Common issues and their solutions.

## AWS

### Resource Explorer: "No aggregator index found" or 401 Unauthorized on Search

Argus needs an aggregator index **and a default view** in `RESOURCE_EXPLORER_REGION`
(default `us-east-1`). Search fails with `401 Unauthorized` if the region has no default view.
Create both:

```bash
aws resource-explorer-2 create-index --region us-east-1
INDEX_ARN=$(aws resource-explorer-2 get-index --region us-east-1 --query Arn --output text)
aws resource-explorer-2 update-index-type --arn "$INDEX_ARN" --type AGGREGATOR --region us-east-1

# Search uses the region's default view; include tags so Argus sees them
VIEW_ARN=$(aws resource-explorer-2 create-view --view-name argus-all \
  --included-properties Name=tags --region us-east-1 --query View.ViewArn --output text)
aws resource-explorer-2 associate-default-view --view-arn "$VIEW_ARN" --region us-east-1
```

The aggregator index can take a while to replicate resources from all regions after it's created.
If resources show no tags, the default view is missing the `tags` property.

### Cost Explorer: "OptInRequired" or all costs show $0

Cost Explorer must be activated in the AWS console before the API works:

1. Go to **AWS Cost Management → Cost Explorer**
2. Click **Launch Cost Explorer** (one-time activation, takes up to 24 hours)

### Bedrock: "AccessDeniedException" for model invocation

You need to enable model access in the Bedrock console:

1. Go to **Amazon Bedrock → Model catalog** (or search "Bedrock" in the AWS console and open **Model access** from the left nav)
2. Find **Claude Sonnet** (Anthropic) and click **Request access** / **Enable**
3. Access is usually granted instantly for Sonnet

Make sure `BEDROCK_REGION` matches the region where you enabled model access.

### Bedrock: "INVALID_PAYMENT_INSTRUMENT"

This is a billing issue, not an IAM issue. AWS requires a valid payment method on the account before Bedrock can be used.

1. Go to **AWS Console → Account Settings → Payment methods**
2. Add or verify a payment method
3. Wait ~1 minute for it to propagate, then retry the scan

### Azure OpenAI: 400 BadRequest for o4-mini / o1 / o3 deployments

Reasoning models require a newer API version than the default (`2024-10-21`):

```ini
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

Argus automatically retries without `temperature` when a reasoning model rejects it — no extra config needed for that.

!!! note
    Check [Azure OpenAI API releases](https://learn.microsoft.com/en-us/azure/ai-services/openai/api-version-deprecation) for the latest stable version that supports your model.

### Pre-signed URL returns 403

The Lambda role needs both `s3:PutObject` and `s3:GetObject` on the report bucket. The SAM templates include both — if you customized IAM, verify the `S3Reports` policy statement.

## GCP

### "Cloud Asset API has not been enabled"

The deploy script enables these APIs automatically (but not Vertex AI). If running manually:

```bash
gcloud services enable \
  cloudasset.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  bigquery.googleapis.com \
  --project=$GOOGLE_CLOUD_PROJECT
```

For the default `AI_PROVIDER=vertexai`, also enable `aiplatform.googleapis.com`.

### Billing data shows $0 for all resources

BigQuery billing export must be enabled:

1. Go to **GCP Console → Billing → Billing export → BigQuery export**
2. Note the full table name (format: `project.dataset.gcp_billing_export_v1_XXXXXX`)
3. Set `BILLING_BQ_TABLE` to the table name

### Signed URL error: "iam.serviceAccounts.signBlob permission"

v4 signed URLs require the service account to have `roles/iam.serviceAccountTokenCreator` **on itself**. The deploy script handles this, but if you configured IAM manually:

```bash
gcloud iam service-accounts add-iam-policy-binding \
  argus-sa@$PROJECT.iam.gserviceaccount.com \
  --member="serviceAccount:argus-sa@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

## Azure

### "AuthorizationFailed" on subscription scan

The managed identity needs **Reader** (and **Cost Management Reader** for cost data) at the subscription level. The Bicep template only assigns roles at the resource group level — you must grant subscription-level roles manually:

```bash
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Reader" \
  --scope /subscriptions/$SUBSCRIPTION_ID
```

### SAS URL returns 403

The managed identity needs two roles on the report storage account:

- **Storage Blob Data Contributor** — read/write blobs
- **Storage Blob Delegator** — required for `get_user_delegation_key()`

The Bicep template assigns both when `reportStorageAccount` is set.

### Azure Functions Core Tools: "command not found"

Install the Azure Functions Core Tools v4:

```bash
# macOS
brew tap azure/functions
brew install azure-functions-core-tools@4

# npm (any OS)
npm install -g azure-functions-core-tools@4
```

## Slack

### Webhook returns HTTP 403 or "invalid_token"

- Verify the webhook URL is correct and hasn't been revoked
- Check that the Slack app hasn't been uninstalled from the workspace
- Create a new webhook at [api.slack.com/apps](https://api.slack.com/apps)

### Webhook returns HTTP 429

Slack rate-limits incoming webhooks to ~1 message per second. Argus sends one message per scan, so this shouldn't happen unless you're running multiple scans simultaneously.

## General

### "SLACK_WEBHOOK_URL is not set"

Every `argus scan` (local or deployed) checks for `SLACK_WEBHOOK_URL` at startup, even if you only
send to Teams or a generic webhook via `NOTIFICATION_PROVIDER`. For local dev, add it to your `.env`
file. For cloud deploys, it's set via the CloudFormation/Bicep/deploy.sh parameters.

To skip delivery during development, set `DRY_RUN=true`.

### Scan finds zero resources

- **AWS**: Verify Resource Explorer has an aggregator index and a default view in `RESOURCE_EXPLORER_REGION`, and has finished indexing
- **All clouds**: Check `EXCLUDE_TAGS` / `EXCLUDE_RESOURCE_TYPES` / `IGNORE_REGIONS` aren't filtering everything out
- **GCP**: Verify `GCP_PROJECT_ID` is set and the service account has `roles/cloudasset.viewer`
- **Azure**: Verify `AZURE_SUBSCRIPTION_IDS` lists valid subscription IDs and Reader is granted
