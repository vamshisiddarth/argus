# Azure Function Deployment

Argus runs as an Azure Function with a Timer trigger on a weekly schedule.

## Prerequisites

- Azure CLI installed and authenticated: `az login`
- [Azure Functions Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local) v4 installed (`func` CLI — needed to publish function code after Bicep deploy)
- A resource group:
  ```bash
  az group create --name Argus-RG --location eastus
  ```
- The subscription IDs you want to scan — you'll need them for `subscriptionIds` parameter
- An Azure OpenAI resource with a GPT-4o deployment **or** an Anthropic API key

## Deploy

```bash
az deployment group create \
  --resource-group Argus-RG \
  --template-file deploy/azure/function-app.bicep \
  --parameters \
      subscriptionIds="sub-id-1,sub-id-2" \
      slackWebhookUrl="https://hooks.slack.com/services/T.../B.../..."
```

### With Azure OpenAI

```bash
az deployment group create \
  --resource-group Argus-RG \
  --template-file deploy/azure/function-app.bicep \
  --parameters \
      subscriptionIds="sub-id-1,sub-id-2" \
      slackWebhookUrl="https://hooks.slack.com/services/..." \
      azureOpenAIEndpoint="https://my-resource.openai.azure.com/" \
      azureOpenAIDeployment="gpt-4o"
```

### With Anthropic API

```bash
az deployment group create \
  --resource-group Argus-RG \
  --template-file deploy/azure/function-app.bicep \
  --parameters \
      subscriptionIds="sub-id-1,sub-id-2" \
      slackWebhookUrl="https://hooks.slack.com/services/..." \
      anthropicApiKey="sk-ant-..."
```

## IAM permissions

The Bicep template creates a system-assigned Managed Identity and binds roles automatically
at the **resource group level**. For cross-subscription scanning you must grant additional
roles at the **subscription level** (see Post-deploy step below).

| Role | Scope | Purpose | Required |
|------|-------|---------|---------|
| `Reader` | Each subscription | Resource Graph, Monitor metrics, Activity Log | Yes |
| `Cost Management Reader` | Each subscription | Cost Management API | Yes for cost data |
| `Monitoring Reader` | Each subscription | Azure Monitor metrics | Included in Reader |
| `Log Analytics Reader` | Log Analytics workspace | Activity Log KQL queries | Only if workspace set |
| `Storage Blob Data Contributor` | Report storage account | Write HTML + JSON reports | Only if `reportStorageAccount` set |

No write permissions on any Azure resource are ever requested.

## Post-deploy: grant subscription access

The Bicep template assigns roles at the resource group level only.
For cross-subscription scanning, grant Reader and Cost Management Reader at the
**subscription level** for each subscription you want to scan:

```bash
# Get the managed identity principal ID from the deployment output
PRINCIPAL_ID=$(az deployment group show \
  --resource-group Argus-RG \
  --name function-app \
  --query properties.outputs.functionAppPrincipalId.value -o tsv)

echo "Principal ID: $PRINCIPAL_ID"

# Grant roles on each subscription (repeat for every subscription to scan)
for SUB_ID in sub-id-1 sub-id-2 sub-id-3; do
  az role assignment create \
    --assignee $PRINCIPAL_ID \
    --role "Reader" \
    --scope /subscriptions/$SUB_ID

  az role assignment create \
    --assignee $PRINCIPAL_ID \
    --role "Cost Management Reader" \
    --scope /subscriptions/$SUB_ID
done
```

Verify the assignments:

```bash
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --query "[].{Role:roleDefinitionName,Scope:scope}" -o table
```

## Multi-subscription setup

To scan multiple subscriptions, see the
[Multi-subscription guide](multi-account.md#azure--multi-subscription-with-managed-identity) — it covers:

- Granting roles across subscriptions (copy-paste `az` commands)
- Configuring `AZURE_SUBSCRIPTION_IDS` or `accounts.yaml`
- Terraform alternative

## Deploy the function code

```bash
func azure functionapp publish <function-app-name>
```

## What gets created

| Resource | Purpose |
|----------|---------|
| Function App (Linux, Python 3.11) | Runs the scan |
| App Service Plan (Consumption Y1) | Serverless billing |
| Storage Account | Required by Function runtime |
| System-assigned managed identity | Authentication to Azure APIs |
| Role assignments | Monitoring Reader + Cost Management Reader at resource group level. Cross-subscription Reader must be granted manually (see post-deploy step above). `Storage Blob Data Contributor` required on the report container if `reportStorageAccount` is set. |

## View logs

```bash
az functionapp log stream --name <function-app-name> --resource-group Argus-RG
```

## Parameters reference

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `subscriptionIds` | Yes | — | Comma-separated subscription IDs |
| `slackWebhookUrl` | Yes | — | Slack incoming webhook URL |
| `azureOpenAIEndpoint` | No | _(empty)_ | Use Azure OpenAI for AI inference |
| `azureOpenAIDeployment` | No | `gpt-4o` | Deployment name |
| `anthropicApiKey` | No | _(empty)_ | Use Anthropic API instead |
| `logAnalyticsWorkspaceId` | No | _(empty)_ | Enables Activity Log KQL queries |
| `scheduleExpression` | No | `0 0 9 * * 1` | Timer cron expression |
| `ignoreRegions` | No | _(empty)_ | Comma-separated Azure regions to skip |
| `dryRun` | No | `false` | `true` to skip Slack post |
| `reportStorageAccount` | No | _(empty)_ | Storage account name for JSON + HTML reports. When set, the Slack digest includes a "Full report" button with a 7-day SAS URL. The Bicep automatically assigns `Storage Blob Data Contributor` to the managed identity on that account. The storage account must already exist in the same subscription. |
| `reportStorageContainer` | No | `argus-reports` | Blob container name (created automatically if missing) |
| `reportUrlExpiry` | No | `604800` | SAS URL expiry in seconds (default: 7 days) |
| `location` | No | resource group location | Azure region for all resources |
