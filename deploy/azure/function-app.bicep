// =============================================================================
// Argus — Azure Function App (Timer trigger)
//
// Deploys:
//   - Azure Function App (Consumption plan) running Argus on a weekly schedule
//   - Storage Account (required by Function App runtime)
//   - App Service Plan (Consumption Y1)
//   - Managed identity with least-privilege read-only roles
//
// Deploy:
//   az group create --name Argus-RG --location eastus
//   az deployment group create \
//     --resource-group Argus-RG \
//     --template-file deploy/azure/function-app.bicep \
//     --parameters subscriptionIds="sub-id-1,sub-id-2" \
//                  slackWebhookUrl="https://hooks.slack.com/services/..."
// =============================================================================

@description('Comma-separated Azure subscription IDs to scan')
param subscriptionIds string

@description('Slack incoming webhook URL')
@secure()
param slackWebhookUrl string

@description('Azure OpenAI endpoint (e.g. https://my-resource.openai.azure.com/). Leave blank to use Anthropic API instead.')
param azureOpenAIEndpoint string = ''

@description('Azure OpenAI GPT-4o deployment name')
param azureOpenAIDeployment string = 'gpt-4o'

@description('Anthropic API key — only required if azureOpenAIEndpoint is not set')
@secure()
param anthropicApiKey string = ''

@description('Log Analytics workspace ID for Activity Log queries (optional)')
param logAnalyticsWorkspaceId string = ''

@description('Cron schedule expression (default: every Monday at 9am UTC)')
param scheduleExpression string = '0 0 9 * * 1'

@description('Comma-separated Azure regions to exclude from the scan')
param ignoreRegions string = ''

@description('Set to "true" to log Slack payload instead of posting')
param dryRun string = 'false'

@description('Log level')
@allowed(['DEBUG', 'INFO', 'WARNING', 'ERROR'])
param logLevel string = 'INFO'

@description('Azure location for all resources')
param location string = resourceGroup().location

@description('Storage account name for HTML + JSON report storage. Leave blank to skip report upload.')
param reportStorageAccount string = ''

@description('Blob container name for reports')
param reportStorageContainer string = 'argus-reports'

@description('SAS URL expiry in seconds (default: 604800 = 7 days)')
param reportUrlExpiry string = '604800'

// ---------------------------------------------------------------------------
// Variables
// ---------------------------------------------------------------------------
var uniqueSuffix = uniqueString(resourceGroup().id)
var storageAccountName = 'argus${take(uniqueSuffix, 10)}'
var functionAppName = 'argus-${uniqueSuffix}'
var hostingPlanName = 'argus-plan-${uniqueSuffix}'
var aiProvider = empty(azureOpenAIEndpoint) ? 'anthropic' : 'azure_openai'

// ---------------------------------------------------------------------------
// Storage Account (required by Function App runtime)
// ---------------------------------------------------------------------------
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

// ---------------------------------------------------------------------------
// Consumption App Service Plan
// ---------------------------------------------------------------------------
resource hostingPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: hostingPlanName
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true  // Linux
  }
}

// ---------------------------------------------------------------------------
// Function App
// ---------------------------------------------------------------------------
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    siteConfig: {
      linuxFxVersion: 'Python|3.13'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'AZURE_SUBSCRIPTION_IDS'
          value: subscriptionIds
        }
        {
          name: 'SLACK_WEBHOOK_URL'
          value: slackWebhookUrl
        }
        {
          name: 'AI_PROVIDER'
          value: aiProvider
        }
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: azureOpenAIEndpoint
        }
        {
          name: 'AZURE_OPENAI_DEPLOYMENT'
          value: azureOpenAIDeployment
        }
        {
          name: 'ANTHROPIC_API_KEY'
          value: anthropicApiKey
        }
        {
          name: 'AZURE_LOG_ANALYTICS_WORKSPACE_ID'
          value: logAnalyticsWorkspaceId
        }
        {
          name: 'IGNORE_REGIONS'
          value: ignoreRegions
        }
        {
          name: 'DRY_RUN'
          value: dryRun
        }
        {
          name: 'LOG_LEVEL'
          value: logLevel
        }
        {
          name: 'ARGUS_SCHEDULE'
          value: scheduleExpression
        }
        {
          name: 'REPORT_STORAGE_ACCOUNT'
          value: reportStorageAccount
        }
        {
          name: 'REPORT_STORAGE_CONTAINER'
          value: reportStorageContainer
        }
        {
          name: 'REPORT_URL_EXPIRY'
          value: reportUrlExpiry
        }
      ]
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
    httpsOnly: true
  }
}

// ---------------------------------------------------------------------------
// IAM — assign read-only roles to the managed identity
// Reader on each subscription must be done separately via CLI after deploy:
//   az role assignment create \
//     --assignee <principalId> \
//     --role "Reader" \
//     --scope /subscriptions/<sub-id>
//
// We assign Monitoring Reader + Cost Management Reader at the resource group
// level here as a starting point.
// ---------------------------------------------------------------------------
var monitoringReaderRoleId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
var costManagementReaderRoleId = '72fafb9e-0641-4937-9268-a91bfd8191a3'

resource monitoringReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, functionApp.id, monitoringReaderRoleId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource costManagementReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, functionApp.id, costManagementReaderRoleId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', costManagementReaderRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Role assignment: Storage Blob Data Contributor on the report storage account
// Only assigned when reportStorageAccount is provided.
// ---------------------------------------------------------------------------
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource reportStorageAccountRef 'Microsoft.Storage/storageAccounts@2023-01-01' existing = if (!empty(reportStorageAccount)) {
  name: reportStorageAccount
}

resource reportStorageBlobContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(reportStorageAccount)) {
  name: guid(reportStorageAccount, functionApp.id, storageBlobDataContributorRoleId)
  scope: reportStorageAccountRef
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output functionAppName string = functionApp.name
output functionAppPrincipalId string = functionApp.identity.principalId
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'

output postDeployInstructions string = '''
After deploy, grant subscription-level Reader access to the managed identity:

  az role assignment create \\
    --assignee ${functionApp.identity.principalId} \\
    --role "Reader" \\
    --scope /subscriptions/<your-subscription-id>

Then deploy the function code:

  func azure functionapp publish ${functionApp.name}
'''
