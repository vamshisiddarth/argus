#!/usr/bin/env bash
# =============================================================================
# Argus — GCP Cloud Run Job deploy script
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - Application Default Credentials set up (gcloud auth application-default login)
#   - Cloud Run API, Cloud Scheduler API, Artifact Registry API enabled
#   - BigQuery billing export configured (optional but recommended)
#
# Usage:
#   bash deploy/gcp/deploy.sh
#
# Required environment variables (set before running):
#   GOOGLE_CLOUD_PROJECT     GCP project ID
#   SLACK_WEBHOOK_URL        Slack incoming webhook URL
#
# Optional environment variables:
#   REGION                   GCP region (default: us-central1)
#   BILLING_BQ_TABLE         BigQuery billing export table
#   SCHEDULE                 Cron expression (default: "0 9 * * 1" = Mondays 9am UTC)
#   DRY_RUN                  "true" to skip Slack post
# =============================================================================
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT must be set}"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:?SLACK_WEBHOOK_URL must be set}"
REGION="${REGION:-us-central1}"
SCHEDULE="${SCHEDULE:-0 9 * * 1}"
SERVICE_NAME="argus"
IMAGE="gcr.io/${PROJECT}/${SERVICE_NAME}:latest"
SA_NAME="argus-sa"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

echo "=== Argus GCP Deploy ==="
echo "Project:  ${PROJECT}"
echo "Region:   ${REGION}"
echo "Image:    ${IMAGE}"
echo "Schedule: ${SCHEDULE}"
echo ""

# ---------------------------------------------------------------------------
# 1. Enable required APIs
# ---------------------------------------------------------------------------
echo "--- Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  cloudasset.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  bigquery.googleapis.com \
  --project="${PROJECT}" \
  --quiet

# ---------------------------------------------------------------------------
# 2. Create service account (idempotent)
# ---------------------------------------------------------------------------
echo "--- Creating service account ${SA_EMAIL}..."
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Argus Cloud Run SA" \
  --project="${PROJECT}" \
  --quiet 2>/dev/null || echo "Service account already exists."

# Grant required read-only roles
ROLES=(
  "roles/cloudasset.viewer"
  "roles/monitoring.viewer"
  "roles/logging.viewer"
  "roles/bigquery.dataViewer"
  "roles/bigquery.jobUser"
)
for role in "${ROLES[@]}"; do
  echo "  Granting ${role}..."
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" \
    --quiet > /dev/null
done

# Grant Vertex AI User for AI inference
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" \
  --quiet > /dev/null

# ---------------------------------------------------------------------------
# 3. Build and push the container image
# ---------------------------------------------------------------------------
echo "--- Building and pushing container image..."
gcloud builds submit . \
  --tag="${IMAGE}" \
  --project="${PROJECT}" \
  --quiet

# ---------------------------------------------------------------------------
# 4. Deploy Cloud Run Job
# ---------------------------------------------------------------------------
echo "--- Deploying Cloud Run Job..."
ENV_VARS="GCP_PROJECT_ID=${PROJECT},SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL},AI_PROVIDER=vertexai,VERTEXAI_PROJECT=${PROJECT},VERTEXAI_LOCATION=${REGION},LOG_LEVEL=INFO"

if [[ -n "${BILLING_BQ_TABLE:-}" ]]; then
  ENV_VARS="${ENV_VARS},BILLING_BQ_TABLE=${BILLING_BQ_TABLE}"
fi
if [[ "${DRY_RUN:-false}" == "true" ]]; then
  ENV_VARS="${ENV_VARS},DRY_RUN=true"
fi

gcloud run jobs create "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="${ENV_VARS}" \
  --memory="512Mi" \
  --cpu="1" \
  --max-retries=1 \
  --task-timeout="3600s" \
  --project="${PROJECT}" \
  --quiet 2>/dev/null || \
gcloud run jobs update "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="${ENV_VARS}" \
  --memory="512Mi" \
  --cpu="1" \
  --max-retries=1 \
  --task-timeout="3600s" \
  --project="${PROJECT}" \
  --quiet

# ---------------------------------------------------------------------------
# 5. Create Cloud Scheduler job
# ---------------------------------------------------------------------------
echo "--- Creating Cloud Scheduler job (schedule: '${SCHEDULE}')..."
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${SERVICE_NAME}:run"

gcloud scheduler jobs create http "argus-weekly" \
  --schedule="${SCHEDULE}" \
  --uri="${JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${SA_EMAIL}" \
  --location="${REGION}" \
  --project="${PROJECT}" \
  --quiet 2>/dev/null || \
gcloud scheduler jobs update http "argus-weekly" \
  --schedule="${SCHEDULE}" \
  --uri="${JOB_URI}" \
  --http-method=POST \
  --oauth-service-account-email="${SA_EMAIL}" \
  --location="${REGION}" \
  --project="${PROJECT}" \
  --quiet

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== Deploy complete! ==="
echo ""
echo "Run a test scan now:"
echo "  gcloud run jobs execute ${SERVICE_NAME} --region=${REGION} --project=${PROJECT}"
echo ""
echo "View logs:"
echo "  gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME}' --project=${PROJECT} --limit=50"
