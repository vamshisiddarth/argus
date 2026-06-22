# Multi-Account / Multi-Project / Multi-Subscription

Argus can scan multiple accounts, projects, or subscriptions in a single run and merge all
findings into one report. The mechanism differs per cloud to match each platform's native
auth model.

---

## AWS — Hub/Spoke with STS AssumeRole

See the dedicated [AWS multi-account guide](aws.md#multi-account) for full setup steps.

Quick summary:

```
Hub Account (runs Argus Lambda)
│
├── sts:AssumeRole → Account A (dev)     → scan → findings
├── sts:AssumeRole → Account B (staging) → scan → findings
└── sts:AssumeRole → Account C (prod)    → scan → findings
                                                  │
                                       Single merged Slack report
```

```yaml title="accounts.yaml"
mode: multi

accounts:
  - id: "111122223333"
    name: dev
    role_arn: arn:aws:iam::111122223333:role/ArgusSpokeRole
  - id: "444455556666"
    name: staging
    role_arn: arn:aws:iam::444455556666:role/ArgusSpokeRole
```

```bash
argus scan --cloud aws --accounts accounts.yaml
```

---

## GCP — Multi-Project with ADC

GCP uses Application Default Credentials (ADC) for auth — there is no STS AssumeRole
equivalent. A single service account granted viewer roles across all target projects is
the idiomatic pattern.

### Architecture

```
Single service account (argus-sa@hub-project.iam.gserviceaccount.com)
│
├── cloudasset.viewer + monitoring.viewer + logging.viewer → Project A
├── cloudasset.viewer + monitoring.viewer + logging.viewer → Project B
└── cloudasset.viewer + monitoring.viewer + logging.viewer → Project C
                                                             │
                                                  One scan loop per project
                                                  Findings merged into one report
```

### Step 1 — Create the service account (once, in your hub project)

```bash
export HUB_PROJECT=my-hub-project
export SA_NAME=argus-sa

gcloud iam service-accounts create $SA_NAME \
  --display-name="Argus scanner" \
  --project=$HUB_PROJECT

export SA_EMAIL="${SA_NAME}@${HUB_PROJECT}.iam.gserviceaccount.com"
```

### Step 2 — Grant roles in each target project

Run this block for **every project** you want Argus to scan:

```bash
export TARGET_PROJECT=my-target-project   # repeat for each project

# Resource discovery
gcloud projects add-iam-policy-binding $TARGET_PROJECT \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudasset.viewer"

# Metrics
gcloud projects add-iam-policy-binding $TARGET_PROJECT \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/monitoring.viewer"

# Last-activity timestamps
gcloud projects add-iam-policy-binding $TARGET_PROJECT \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/logging.viewer"

# Cost data (BigQuery billing export — only needed in the billing project)
gcloud projects add-iam-policy-binding $TARGET_PROJECT \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.dataViewer"

gcloud projects add-iam-policy-binding $TARGET_PROJECT \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser"
```

Minimum roles summary:

| Role | Purpose | Required |
|------|---------|---------|
| `roles/cloudasset.viewer` | List all resources (Asset Inventory) | Yes |
| `roles/monitoring.viewer` | Read metrics (Cloud Monitoring) | Yes |
| `roles/logging.viewer` | Read audit logs (Cloud Logging) | Yes |
| `roles/bigquery.dataViewer` | Read billing export table | Only for cost data |
| `roles/bigquery.jobUser` | Run BigQuery queries | Only for cost data |
| `roles/aiplatform.user` | Invoke Vertex AI models | Only if `AI_PROVIDER=vertexai` |

### Step 3 — Allow Cloud Run Job to impersonate the service account

If Argus runs as a Cloud Run Job, grant the Compute default SA (or Cloud Run SA) permission
to act as the Argus SA:

```bash
# Get the Cloud Run Job's service account
export CLOUD_RUN_SA=$(gcloud run jobs describe argus \
  --region=us-central1 \
  --project=$HUB_PROJECT \
  --format='value(spec.template.spec.serviceAccountName)')

gcloud iam service-accounts add-iam-policy-binding ${SA_EMAIL} \
  --member="serviceAccount:${CLOUD_RUN_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project=$HUB_PROJECT
```

For **local dev**, authenticate as the SA directly:

```bash
gcloud auth application-default login --impersonate-service-account=$SA_EMAIL
```

### Step 4 — Configure multi-project scanning

**Option A — environment variable (simplest):**

```bash
export GCP_PROJECT_IDS=proj-dev,proj-staging,proj-prod
argus scan --cloud gcp
```

**Option B — accounts.yaml (recommended for named projects):**

```yaml title="accounts.yaml"
mode: multi

projects:
  - id: proj-dev
    name: dev
  - id: proj-staging
    name: staging
  - id: proj-prod
    name: production
```

```bash
argus scan --cloud gcp --accounts accounts.yaml
```

**Option C — Cloud Run Job environment (deployed):**

Set `GCP_PROJECT_IDS=proj-dev,proj-staging,proj-prod` in the Cloud Run Job's
environment variables via the GCP Console or:

```bash
gcloud run jobs update argus \
  --region=us-central1 \
  --project=$HUB_PROJECT \
  --update-env-vars GCP_PROJECT_IDS=proj-dev,proj-staging,proj-prod
```

### Terraform alternative

```hcl
locals {
  argus_sa_email = "argus-sa@${var.hub_project}.iam.gserviceaccount.com"
  target_projects = ["proj-dev", "proj-staging", "proj-prod"]
  argus_roles = [
    "roles/cloudasset.viewer",
    "roles/monitoring.viewer",
    "roles/logging.viewer",
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
  ]
}

resource "google_service_account" "argus" {
  project      = var.hub_project
  account_id   = "argus-sa"
  display_name = "Argus scanner"
}

resource "google_project_iam_member" "argus_roles" {
  for_each = toset([
    for pair in setproduct(local.target_projects, local.argus_roles) :
    "${pair[0]}/${pair[1]}"
  ])

  project = split("/", each.key)[0]
  role    = split("/", each.key)[1]
  member  = "serviceAccount:${google_service_account.argus.email}"
}
```

---

## Azure — Multi-Subscription with Managed Identity

Azure Resource Graph queries all subscriptions in a single API call — there is no
per-subscription scan loop. The Managed Identity running the Function App needs
Reader + Cost Management Reader across every target subscription.

### Architecture

```
Function App (system-assigned Managed Identity)
│
├── Reader + Cost Management Reader → Subscription A
├── Reader + Cost Management Reader → Subscription B
└── Reader + Cost Management Reader → Subscription C
                │
        Single Resource Graph query across all subscriptions
        Cost Management API batched per subscription
        One merged report
```

### Step 1 — Get the Managed Identity principal ID

After deploying the Function App (via Bicep), retrieve the identity:

```bash
export RG=Argus-RG
export FUNC_APP=<your-function-app-name>

export PRINCIPAL_ID=$(az functionapp identity show \
  --name $FUNC_APP \
  --resource-group $RG \
  --query principalId -o tsv)

echo "Principal ID: $PRINCIPAL_ID"
```

### Step 2 — Grant roles on each subscription

Run this block for **every subscription** you want Argus to scan:

```bash
export SUB_ID=aaaabbbb-cccc-dddd-eeee-ffffffffffff   # repeat for each subscription

# Resource discovery and metrics
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Reader" \
  --scope /subscriptions/$SUB_ID

# Cost data
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Cost Management Reader" \
  --scope /subscriptions/$SUB_ID
```

Role summary:

| Role | Scope | Purpose | Required |
|------|-------|---------|---------|
| `Reader` | Each subscription | Resource Graph, Monitor metrics, Activity Log | Yes |
| `Cost Management Reader` | Each subscription | Cost Management API | Yes for cost data |
| `Log Analytics Reader` | Log Analytics workspace | Activity Log KQL queries | Only if `AZURE_LOG_ANALYTICS_WORKSPACE_ID` is set |

### Step 3 — Configure multi-subscription scanning

**Option A — environment variable:**

```bash
export AZURE_SUBSCRIPTION_IDS=sub-id-1,sub-id-2,sub-id-3
argus scan --cloud azure
```

**Option B — accounts.yaml (recommended for named subscriptions):**

```yaml title="accounts.yaml"
mode: multi

subscriptions:
  - id: "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
    name: dev
  - id: "11112222-3333-4444-5555-666677778888"
    name: staging
  - id: "99990000-aaaa-bbbb-cccc-ddddeeeeffffgg"
    name: production
```

```bash
argus scan --cloud azure --accounts accounts.yaml
```

**Option C — Function App environment (deployed):**

```bash
az functionapp config appsettings set \
  --name $FUNC_APP \
  --resource-group $RG \
  --settings AZURE_SUBSCRIPTION_IDS="sub-id-1,sub-id-2,sub-id-3"
```

### Terraform alternative

```hcl
locals {
  subscription_ids = [
    "aaaabbbb-cccc-dddd-eeee-ffffffffffff",
    "11112222-3333-4444-5555-666677778888",
  ]
  argus_roles = ["Reader", "Cost Management Reader"]
}

data "azurerm_function_app" "argus" {
  name                = var.function_app_name
  resource_group_name = var.resource_group_name
}

resource "azurerm_role_assignment" "argus" {
  for_each = toset([
    for pair in setproduct(local.subscription_ids, local.argus_roles) :
    "${pair[0]}/${pair[1]}"
  ])

  scope                = "/subscriptions/${split("/", each.key)[0]}"
  role_definition_name = split("/", each.key)[1]
  principal_id         = data.azurerm_function_app.argus.identity[0].principal_id
}
```

### Log Analytics (optional, for richer last-activity data)

If you have a Log Analytics workspace collecting activity logs:

```bash
export WORKSPACE_ID=<log-analytics-workspace-id>

az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Log Analytics Reader" \
  --scope /subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/$WORKSPACE_ID
```

Then set in the Function App:

```bash
az functionapp config appsettings set \
  --name $FUNC_APP \
  --resource-group $RG \
  --settings AZURE_LOG_ANALYTICS_WORKSPACE_ID=$WORKSPACE_ID
```

---

## Troubleshooting

### GCP: "Permission denied on project X"

The service account is missing a role on that project. Re-run Step 2 for the failing project
and check with:

```bash
gcloud projects get-iam-policy $TARGET_PROJECT \
  --flatten="bindings[].members" \
  --filter="bindings.members:${SA_EMAIL}" \
  --format="table(bindings.role)"
```

### Azure: "AuthorizationFailed" on a subscription

The Managed Identity is missing Reader on that subscription. Re-run Step 2 for the failing
subscription and verify:

```bash
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --scope /subscriptions/$SUB_ID \
  --query "[].{Role:roleDefinitionName,Scope:scope}" -o table
```

### Partial scan failures

If one project or subscription fails, Argus logs the error and continues with the others.
Check the logs to identify which failed:

```bash
# GCP Cloud Run logs
gcloud logging read \
  'resource.type=cloud_run_job AND jsonPayload.event="project_scan_failed"' \
  --project=$HUB_PROJECT --limit=20

# Azure Function logs
az functionapp log stream --name $FUNC_APP --resource-group $RG
```
