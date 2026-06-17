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

## Post-deploy: grant subscription Reader access

The Bicep template assigns roles at the resource group level.
For cross-subscription scanning, grant Reader access at the subscription level:

```bash
# Get the managed identity principal ID from the deployment output
PRINCIPAL_ID=$(az deployment group show \
  --resource-group Argus-RG \
  --name function-app \
  --query properties.outputs.functionAppPrincipalId.value -o tsv)

# Grant Reader on each subscription
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Reader" \
  --scope /subscriptions/sub-id-1

az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Reader" \
  --scope /subscriptions/sub-id-2
```

## Deploy the function code

```bash
func azure functionapp publish <function-app-name>
```

## What gets created

| Resource | Purpose |
|----------|---------|
| Function App (Linux, Python 3.13) | Runs the scan |
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
| `reportStorageAccount` | No | _(empty)_ | Storage account name for JSON + HTML reports. When set, the Slack digest includes a "Full report" button with a 7-day SAS URL. The managed identity needs `Storage Blob Data Contributor` on the container. |
| `reportStorageContainer` | No | `argus-reports` | Blob container name (created automatically if missing) |
| `reportUrlExpiry` | No | `604800` | SAS URL expiry in seconds (default: 7 days) |
| `location` | No | resource group location | Azure region for all resources |
