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

---

## IAM permissions

The Bicep template creates a system-assigned Managed Identity for the Function App.
All permissions are **read-only** — Argus never writes to any Azure resource.

### What each adapter method calls

| Adapter method | Azure API called | Azure SDK client |
|---------------|-----------------|-----------------|
| `list_resources` | `POST /providers/Microsoft.ResourceGraph/resources` (KQL query) | `ResourceGraphClient.resources()` |
| `get_metrics` | `GET /subscriptions/{sub}/resourceGroups/.../providers/.../metrics` | `MetricsQueryClient.query_resource()` + `list_metric_definitions()` |
| `get_cost` | `POST /subscriptions/{sub}/providers/Microsoft.CostManagement/query` | `CostManagementClient.query.usage()` |
| `get_last_activity` | Log Analytics: `POST /workspaces/{id}/query` (KQL) | `LogsQueryClient.query_workspace()` |
| `get_last_activity` (fallback) | `GET /subscriptions/{sub}/providers/microsoft.insights/eventtypes/management/values` | `MonitorManagementClient.activity_logs.list()` |

### Required roles (minimum)

| Role | Scope | Azure permissions granted | Used by | Required |
|------|-------|--------------------------|---------|----------|
| `Reader` | Each subscription | `*/read` on all resource types | Resource Graph KQL, Monitor metrics, Activity Log fallback | **Yes** |
| `Cost Management Reader` | Each subscription | `Microsoft.CostManagement/query/action`, `Microsoft.CostManagement/*/read` | Cost Management API for spend data | **Yes** for cost data |
| `Log Analytics Reader` | Log Analytics workspace | `Microsoft.OperationalInsights/workspaces/read`, `*/query/read` | Activity Log KQL queries via Log Analytics | Optional¹ |
| `Storage Blob Data Contributor` | Report storage account | `Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*` | Write JSON + HTML reports, generate SAS URLs | Optional² |

> ¹ Required only when `logAnalyticsWorkspaceId` is set. Without it, Argus falls back to the Activity Log REST API (covered by `Reader`).  
> ² Required only when `reportStorageAccount` is set.

### Custom role (minimum permission surface)

If you want tighter control than the built-in roles, create a custom role with only the
exact actions Argus calls:

```json
{
  "Name": "Argus Scanner",
  "Description": "Minimum read-only permissions for Argus cost optimizer",
  "IsCustom": true,
  "Actions": [
    "Microsoft.ResourceGraph/resources/action",
    "Microsoft.Insights/metrics/read",
    "Microsoft.Insights/metricDefinitions/read",
    "Microsoft.Insights/eventtypes/management/values/read",
    "Microsoft.CostManagement/query/action",
    "Microsoft.CostManagement/*/read"
  ],
  "NotActions": [],
  "DataActions": [
    "Microsoft.OperationalInsights/workspaces/query/read"
  ],
  "AssignableScopes": [
    "/subscriptions/YOUR-SUB-ID"
  ]
}
```

```bash
# Save the JSON above as argus-custom-role.json, then:
az role definition create --role-definition argus-custom-role.json

az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Argus Scanner" \
  --scope /subscriptions/YOUR-SUB-ID
```

> **Note:** Most users should use built-in `Reader` + `Cost Management Reader` — they are
> simpler, pre-audited by Microsoft, and cover all Argus operations. The custom role above
> is for environments with strict role minimization requirements.

### Grant roles: copy-paste commands

```bash
# Step 1: get the managed identity principal ID from the deployment output
PRINCIPAL_ID=$(az deployment group show \
  --resource-group Argus-RG \
  --name function-app \
  --query properties.outputs.functionAppPrincipalId.value -o tsv)

echo "Managed Identity Principal ID: $PRINCIPAL_ID"

# Step 2: grant Reader + Cost Management Reader on every subscription to scan
for SUB_ID in sub-id-1 sub-id-2 sub-id-3; do
  echo "Granting roles on subscription: $SUB_ID"

  az role assignment create \
    --assignee $PRINCIPAL_ID \
    --role "Reader" \
    --scope /subscriptions/$SUB_ID

  az role assignment create \
    --assignee $PRINCIPAL_ID \
    --role "Cost Management Reader" \
    --scope /subscriptions/$SUB_ID
done

# Step 3 (optional): grant Log Analytics Reader for richer activity data
LOG_WORKSPACE_ID="/subscriptions/sub-id-1/resourceGroups/my-rg/providers/Microsoft.OperationalInsights/workspaces/my-workspace"
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Log Analytics Reader" \
  --scope $LOG_WORKSPACE_ID

# Step 4 (optional): grant Storage Blob Data Contributor for HTML report uploads
STORAGE_ACCOUNT_ID="/subscriptions/sub-id-1/resourceGroups/my-rg/providers/Microsoft.Storage/storageAccounts/myreportstore"
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope $STORAGE_ACCOUNT_ID
```

### Verify the assignments

```bash
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --query "[].{Role:roleDefinitionName,Scope:scope}" \
  --output table
```

Expected output:
```
Role                        Scope
--------------------------  ------------------------------------------
Reader                      /subscriptions/sub-id-1
Cost Management Reader      /subscriptions/sub-id-1
Reader                      /subscriptions/sub-id-2
Cost Management Reader      /subscriptions/sub-id-2
```

### Terraform equivalent

```hcl
data "azurerm_subscription" "targets" {
  for_each        = toset(var.subscription_ids)
  subscription_id = each.value
}

# Reader — covers Resource Graph, Monitor metrics, Activity Log fallback
resource "azurerm_role_assignment" "argus_reader" {
  for_each             = data.azurerm_subscription.targets
  principal_id         = azurerm_linux_function_app.argus.identity[0].principal_id
  role_definition_name = "Reader"
  scope                = each.value.id
}

# Cost Management Reader — covers CostManagement/query/action
resource "azurerm_role_assignment" "argus_cost" {
  for_each             = data.azurerm_subscription.targets
  principal_id         = azurerm_linux_function_app.argus.identity[0].principal_id
  role_definition_name = "Cost Management Reader"
  scope                = each.value.id
}

# Log Analytics Reader — optional, only if log_analytics_workspace_id is set
resource "azurerm_role_assignment" "argus_logs" {
  count                = var.log_analytics_workspace_id != "" ? 1 : 0
  principal_id         = azurerm_linux_function_app.argus.identity[0].principal_id
  role_definition_name = "Log Analytics Reader"
  scope                = var.log_analytics_workspace_id
}
```

### Why `Reader` is sufficient for most operations

Azure's `Reader` role includes `*/read` on all resource providers. This covers:

- `Microsoft.ResourceGraph/resources/action` — Resource Graph KQL queries
- `microsoft.insights/metrics/read` — Monitor metrics for all resource types
- `microsoft.insights/eventtypes/management/values/read` — Activity Log fallback

`Cost Management Reader` is a separate role because cost data is scoped to billing, not resources, and `Reader` does not include `Microsoft.CostManagement/query/action`.

---

## Post-deploy: deploy the function code

```bash
func azure functionapp publish <function-app-name>
```

## What gets created

| Resource | Purpose |
|----------|---------|
| Function App (Linux, Python 3.11) | Runs the scan |
| App Service Plan (Consumption Y1) | Serverless billing |
| Storage Account | Required by Function runtime |
| System-assigned managed identity | Authentication to Azure APIs — no credentials stored |
| Role assignments | `Reader` + `Cost Management Reader` at resource group level. Cross-subscription access must be granted manually (see above). |

## View logs

```bash
az functionapp log stream --name <function-app-name> --resource-group Argus-RG
```

---

## Multi-subscription setup

To scan multiple subscriptions in one run, see the
[Multi-subscription guide](multi-account.md#azure--multi-subscription-with-managed-identity) — it covers:

- Granting roles across subscriptions (the `for` loop above works for this)
- Configuring `AZURE_SUBSCRIPTION_IDS` or `ACCOUNTS_CONFIG`
- Terraform alternative

---

## Parameters reference

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `subscriptionIds` | Yes | — | Comma-separated subscription IDs |
| `slackWebhookUrl` | Yes | — | Slack incoming webhook URL |
| `azureOpenAIEndpoint` | No | _(empty)_ | Use Azure OpenAI for AI inference |
| `azureOpenAIDeployment` | No | `gpt-4o` | Deployment name |
| `anthropicApiKey` | No | _(empty)_ | Use Anthropic API instead |
| `logAnalyticsWorkspaceId` | No | _(empty)_ | Enables Activity Log KQL queries (richer last-activity data) |
| `scheduleExpression` | No | `0 0 9 * * 1` | Timer cron expression |
| `ignoreRegions` | No | _(empty)_ | Comma-separated Azure regions to skip |
| `dryRun` | No | `false` | `true` to skip Slack post |
| `reportStorageAccount` | No | _(empty)_ | Storage account name for JSON + HTML reports. When set, the Slack digest includes a "Full report" button with a 7-day SAS URL. The Bicep automatically assigns `Storage Blob Data Contributor` to the managed identity. The storage account must already exist in the same subscription. |
| `reportStorageContainer` | No | `argus-reports` | Blob container name (created automatically if missing) |
| `reportUrlExpiry` | No | `604800` | SAS URL expiry in seconds (default: 7 days) |
| `location` | No | resource group location | Azure region for all resources |
