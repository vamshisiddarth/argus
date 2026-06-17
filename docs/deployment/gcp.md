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
| IAM bindings | `cloudasset.viewer`, `monitoring.viewer`, `logging.viewer`, `bigquery.dataViewer`, `aiplatform.user` |

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

## Cost data setup

For per-resource cost data, enable BigQuery billing export:

1. GCP Console → **Billing → Billing export → BigQuery export**
2. Note the table name (format: `project.dataset.gcp_billing_export_v1_XXXXXX`)
3. Set `BILLING_BQ_TABLE` in the Cloud Run Job environment variables

Without this, cost fields show `$0.00` — the agent still finds idle resources via metrics and audit logs.
