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
#   REPORT_GCS_BUCKET        GCS bucket for HTML + JSON reports (created automatically if set)
#   REPORT_URL_EXPIRY        Signed URL expiry in seconds (default: 604800 = 7 days)
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

# ---------------------------------------------------------------------------
# Preflight — validate required tools and APIs before touching anything
# ---------------------------------------------------------------------------
echo "--- Preflight checks..."

if ! command -v gcloud &>/dev/null; then
  echo "ERROR: gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
  exit 1
fi

if ! gcloud auth print-access-token &>/dev/null; then
  echo "ERROR: gcloud not authenticated. Run: gcloud auth login"
  exit 1
fi

if ! gcloud auth application-default print-access-token &>/dev/null; then
  echo "ERROR: Application Default Credentials not configured."
  echo "  Run: gcloud auth application-default login"
  echo "  Then: gcloud auth application-default set-quota-project ${PROJECT}"
  exit 1
fi

echo "  ✓ gcloud authenticated"
echo ""

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
echo "--- Building and pushing container image (CLOUD=gcp)..."
gcloud builds submit . \
  --tag="${IMAGE}" \
  --build-arg="CLOUD=gcp" \
  --project="${PROJECT}" \
  --quiet

# ---------------------------------------------------------------------------
# 4. Deploy Cloud Run Job
# ---------------------------------------------------------------------------
echo "--- Deploying Cloud Run Job..."
AI_PROVIDER_VALUE="${AI_PROVIDER:-vertexai}"
ENV_VARS="GCP_PROJECT_ID=${PROJECT},SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL},AI_PROVIDER=${AI_PROVIDER_VALUE},VERTEXAI_PROJECT=${PROJECT},VERTEXAI_LOCATION=${REGION},LOG_LEVEL=INFO"
if [[ "${AI_PROVIDER_VALUE}" == "anthropic" && -n "${ANTHROPIC_API_KEY:-}" ]]; then
  ENV_VARS="${ENV_VARS},ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
fi

if [[ -n "${BILLING_BQ_TABLE:-}" ]]; then
  ENV_VARS="${ENV_VARS},BILLING_BQ_TABLE=${BILLING_BQ_TABLE}"
fi
if [[ "${DRY_RUN:-false}" == "true" ]]; then
  ENV_VARS="${ENV_VARS},DRY_RUN=true"
fi

# Optional: GCS bucket for HTML + JSON reports
if [[ -n "${REPORT_GCS_BUCKET:-}" ]]; then
  echo "--- Setting up GCS report bucket: ${REPORT_GCS_BUCKET}..."
  # Enable GCS API
  gcloud services enable storage.googleapis.com --project="${PROJECT}" --quiet

  # Create bucket if it doesn't exist (uniform bucket-level access, private)
  gcloud storage buckets create "gs://${REPORT_GCS_BUCKET}" \
    --project="${PROJECT}" \
    --location="${REGION}" \
    --uniform-bucket-level-access \
    --quiet 2>/dev/null || echo "  Bucket already exists."

  # Grant the service account objectCreator + objectViewer for signed URLs
  gcloud storage buckets add-iam-policy-binding "gs://${REPORT_GCS_BUCKET}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectCreator" \
    --quiet > /dev/null
  gcloud storage buckets add-iam-policy-binding "gs://${REPORT_GCS_BUCKET}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectViewer" \
    --quiet > /dev/null

  # Grant service account token creator on itself (required for v4 signed URLs)
  gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project="${PROJECT}" \
    --quiet > /dev/null

  ENV_VARS="${ENV_VARS},REPORT_GCS_BUCKET=${REPORT_GCS_BUCKET}"
  if [[ -n "${REPORT_URL_EXPIRY:-}" ]]; then
    ENV_VARS="${ENV_VARS},REPORT_URL_EXPIRY=${REPORT_URL_EXPIRY}"
  fi
fi

gcloud run jobs create "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="${ENV_VARS}" \
  --args="scan,--cloud,gcp" \
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
  --args="scan,--cloud,gcp" \
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
