# GCP Cloud Run Deployment

Argus runs as a Cloud Run Job triggered by Cloud Scheduler on a weekly schedule.

## Prerequisites

- `gcloud` CLI installed and authenticated
- Application Default Credentials: `gcloud auth application-default login`
- APIs enabled (the deploy script enables them automatically):
    - Cloud Run, Cloud Scheduler, Artifact Registry
    - Cloud Asset Inventory, Cloud Monitoring, Cloud Logging, BigQuery

## Deploy

```bash
export GOOGLE_CLOUD_PROJECT=my-project-id
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...

bash deploy/gcp/deploy.sh
```

### Optional variables

```bash
export REGION=us-central1              # default: us-central1
export BILLING_BQ_TABLE=my-project.billing.gcp_billing_export_v1_XXX
export SCHEDULE="0 9 * * 1"           # default: Mondays 9am UTC (cron)
export DRY_RUN=true                   # skip Slack post

# HTML report storage (optional — enables "Full report" button in Slack)
export REPORT_GCS_BUCKET=my-argus-reports-bucket
export REPORT_URL_EXPIRY=604800        # 7 days (default)
```

When `REPORT_GCS_BUCKET` is set, the deploy script **automatically**:

- Creates the GCS bucket (if it doesn't exist)
- Grants the service account `storage.objectCreator` + `storage.objectViewer`
- Grants `iam.serviceAccountTokenCreator` on the service account itself (required for v4 signed URLs)
- Sets `REPORT_GCS_BUCKET` in the Cloud Run Job environment

## What gets created

| Resource | Purpose |
|----------|---------|
| Cloud Run Job | Runs the scan |
| Cloud Scheduler job | Triggers the job weekly |
| Service account | `argus-sa@<project>.iam.gserviceaccount.com` |
| IAM bindings | See [IAM permissions](#iam-permissions) below |

## Trigger a manual scan

```bash
gcloud run jobs execute argus \
  --region=us-central1 \
  --project=my-project-id
```

## View logs

```bash
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=argus' \
  --project=my-project-id \
  --limit=50 \
  --format='value(textPayload)'
```

---

## IAM permissions

The deploy script creates `argus-sa@<project>.iam.gserviceaccount.com` and binds these roles
automatically. All permissions are **read-only** — Argus never writes to any cloud resource.

### Minimum required roles

| Role | IAM permissions granted | Used by | Required |
|------|------------------------|---------|----------|
| `roles/cloudasset.viewer` | `cloudasset.assets.listAssets`, `cloudasset.assets.searchAllResources` | Asset Inventory — list all resources across the project | **Yes** |
| `roles/monitoring.viewer` | `monitoring.timeSeries.list`, `monitoring.metricDescriptors.list` | Cloud Monitoring — CPU, memory, request metrics per resource | **Yes** |
| `roles/logging.viewer` | `logging.logEntries.list` | Cloud Audit Logs — last-activity timestamps (Admin Activity + Data Access logs) | **Yes** |
| `roles/bigquery.dataViewer` | `bigquery.tables.getData`, `bigquery.tables.list` | Read the billing export table for cost data | Optional¹ |
| `roles/bigquery.jobUser` | `bigquery.jobs.create` | Run the cost query job | Optional¹ |
| `roles/aiplatform.user` | `aiplatform.endpoints.predict` | Invoke Vertex AI models for AI analysis | Optional² |
| `roles/storage.objectCreator` | `storage.objects.create` | Write JSON + HTML reports to GCS | Optional³ |
| `roles/storage.objectViewer` | `storage.objects.get`, `storage.objects.list` | Read reports, generate signed URLs | Optional³ |
| `roles/iam.serviceAccountTokenCreator` | `iam.serviceAccounts.signBlob` | Sign v4 GCS URLs (self-reference on the SA itself) | Optional³ |

> ¹ Required only when `BILLING_BQ_TABLE` is set. Without it, cost fields show `$0.00`.  
> ² Required only when `AI_PROVIDER=vertexai` (the default for Cloud Run). Set `AI_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` to skip this role entirely.  
> ³ Required only when `REPORT_GCS_BUCKET` is set.

### Minimum viable setup (no cost data, no GCS reports, Anthropic API for AI)

If you want the smallest possible permission surface:

```bash
SA="argus-sa@my-project-id.iam.gserviceaccount.com"
PROJECT="my-project-id"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/cloudasset.viewer"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/monitoring.viewer"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" \
  --role="roles/logging.viewer"
```

Then set `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` — no Vertex AI role needed.

### Full setup (all features enabled)

```bash
SA="argus-sa@my-project-id.iam.gserviceaccount.com"
PROJECT="my-project-id"

for ROLE in \
  roles/cloudasset.viewer \
  roles/monitoring.viewer \
  roles/logging.viewer \
  roles/bigquery.dataViewer \
  roles/bigquery.jobUser \
  roles/aiplatform.user \
  roles/storage.objectCreator \
  roles/storage.objectViewer; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:$SA" \
    --role="$ROLE"
done

# Self-referential binding for GCS signed URLs
gcloud iam service-accounts add-iam-policy-binding $SA \
  --member="serviceAccount:$SA" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project=$PROJECT
```

### Verify permissions

```bash
gcloud projects get-iam-policy my-project-id \
  --flatten="bindings[].members" \
  --filter="bindings.members:argus-sa@my-project-id.iam.gserviceaccount.com" \
  --format="table(bindings.role)"
```

### Terraform equivalent

```hcl
locals {
  argus_sa    = "serviceAccount:argus-sa@${var.project_id}.iam.gserviceaccount.com"
  core_roles  = [
    "roles/cloudasset.viewer",
    "roles/monitoring.viewer",
    "roles/logging.viewer",
  ]
  cost_roles  = [
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
  ]
}

resource "google_project_iam_member" "argus_core" {
  for_each = toset(local.core_roles)
  project  = var.project_id
  role     = each.value
  member   = local.argus_sa
}

resource "google_project_iam_member" "argus_cost" {
  for_each = toset(local.cost_roles)
  project  = var.project_id
  role     = each.value
  member   = local.argus_sa
}

# Only needed when AI_PROVIDER=vertexai
resource "google_project_iam_member" "argus_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = local.argus_sa
}
```

---

## Multi-project setup

To scan multiple GCP projects in one run, see the
[Multi-project guide](multi-account.md#gcp--multi-project-with-adc) — it covers:

- Granting the service account roles across all target projects (copy-paste `gcloud` commands)
- Configuring `GCP_PROJECT_IDS` or `ACCOUNTS_CONFIG`
- Terraform alternative

---

## Cost data setup

For per-resource cost data, enable BigQuery billing export:

1. GCP Console → **Billing → Billing export → BigQuery export**
2. Note the table name (format: `project.dataset.gcp_billing_export_v1_XXXXXX`)
3. Set `BILLING_BQ_TABLE` in the Cloud Run Job environment variables

Without this, cost fields show `$0.00` — the agent still finds idle resources via metrics and audit logs.

### Enable required APIs

The deploy script runs this automatically. To enable manually:

```bash
gcloud services enable \
  cloudasset.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  bigquery.googleapis.com \
  aiplatform.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  --project=my-project-id
```
