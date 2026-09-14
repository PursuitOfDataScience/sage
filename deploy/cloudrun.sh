#!/usr/bin/env bash
# Deploy Sage to Google Cloud Run.
#
# Idempotent: safe to re-run. The first run enables APIs and creates the secret,
# which takes a couple of minutes; later runs just rebuild and redeploy (~90s).
#
#   ./deploy/cloudrun.sh
#
# Prerequisites, all one-time and all interactive (see deploy/README.md):
#   gcloud auth login && gcloud config set project <PROJECT_ID>
set -euo pipefail

PROJECT="$(gcloud config get-value project 2>/dev/null)"
SERVICE="${SERVICE:-sage}"
# us-central1 is one of the regions the Always Free tier actually covers. The free
# grant is region-restricted; deploying to a European region silently forfeits it.
REGION="${REGION:-us-central1}"
SECRET="${SECRET:-sage-openrouter-key}"
GEMINI_SECRET="${GEMINI_SECRET:-sage-gemini-key}"

if [[ -z "$PROJECT" ]]; then
  echo "No project set. Run: gcloud config set project <PROJECT_ID>" >&2
  exit 1
fi

echo "==> Project ${PROJECT}, service ${SERVICE}, region ${REGION}"

# CI deploys with SKIP_SETUP=1. Not an optimisation -- `sage-deployer` deliberately
# has no serviceusage or iam-admin rights, so the one-time block below would fail for
# it. A deploy identity that could enable APIs and mint service accounts would be a
# deploy identity worth stealing.
SKIP_SETUP="${SKIP_SETUP:-0}"

if [[ "$SKIP_SETUP" != "1" ]]; then

# ---------------------------------------------------------------- one-time setup
# Enabling an already-enabled API is a no-op, so this stays in the script rather
# than living in a README step someone skips.
echo "==> Enabling APIs (no-op if already on)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com

# The API key. Created once, interactively, so it never touches the repo or an
# image layer. Rotate with:
#   printf '%s' "$NEW_KEY" | gcloud secrets versions add "$SECRET" --data-file=-
if ! gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  echo "==> Secret ${SECRET} does not exist."
  if [[ ! -t 0 ]]; then
    echo "    No terminal to prompt at. Create it first:" >&2
    echo "    printf '%s' \"\$OPENROUTER_API_KEY\" | gcloud secrets create ${SECRET} --data-file=-" >&2
    exit 1
  fi
  read -rsp "    Paste the OpenRouter key (sk-or-v1-...): " KEY; echo
  printf '%s' "$KEY" | gcloud secrets create "$SECRET" --data-file=- --replication-policy=automatic
  unset KEY
fi

# ------------------------------------------------------------------- identity
# The service runs as an account of its own rather than the project's default
# compute one. Two reasons, and the second is the one that matters.
#
# A project created recently may not HAVE a default compute service account until the
# Compute Engine API is enabled, so assuming `<number>-compute@developer...` exists is
# a confusing way for a first deploy to fail.
#
# And where it does exist it carries roles/editor on the whole project. This service
# is a public URL that feeds reader-supplied text to a model and runs a tool loop --
# giving that project-wide edit rights to read one API key is the wrong trade by
# several orders of magnitude. The account below holds exactly one permission.
RUNTIME_SA="${SERVICE}-run@${PROJECT}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
  echo "==> Creating runtime service account ${RUNTIME_SA}"
  gcloud iam service-accounts create "${SERVICE}-run" \
    --display-name="${SERVICE} Cloud Run runtime"
fi

for S in "$SECRET" "$GEMINI_SECRET"; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done

# The BUILD runs as its own account too, and for a blunter reason than the runtime
# one: on a project created after Google's 2024 change the default compute account
# is no longer granted roles/editor, so `--source` builds fail before they start --
# Cloud Build cannot read the source zip gcloud just uploaded on its behalf. The
# error names `<number>-compute@developer` and reads like a missing account rather
# than a missing grant, which is a slow thing to diagnose on a first deploy.
#
# roles/cloudbuild.builds.builder is the scoped role for this: read the source
# bucket, write the image to Artifact Registry, write build logs. Not editor.
BUILD_SA="${SERVICE}-build@${PROJECT}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$BUILD_SA" >/dev/null 2>&1; then
  echo "==> Creating build service account ${BUILD_SA}"
  gcloud iam service-accounts create "${SERVICE}-build" \
    --display-name="${SERVICE} Cloud Build"
fi

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${BUILD_SA}" \
  --role=roles/cloudbuild.builds.builder >/dev/null

# IAM is eventually consistent and a fresh binding is routinely not visible to the
# build that immediately follows it. Cheap insurance against a spurious first-run
# failure that succeeds on a blind retry.
sleep 10

else
  echo "==> SKIP_SETUP=1, going straight to the deploy"
  RUNTIME_SA="${SERVICE}-run@${PROJECT}.iam.gserviceaccount.com"
  BUILD_SA="${SERVICE}-build@${PROJECT}.iam.gserviceaccount.com"
fi

# ---------------------------------------------------------------------- deploy
# --source builds with Cloud Build and pushes to Artifact Registry, so no local
# Docker daemon is needed -- which is the whole reason this works from a login node.
echo "==> Building and deploying"
gcloud run deploy "$SERVICE" \
  --source=. \
  --region="$REGION" \
  --allow-unauthenticated \
  --service-account="$RUNTIME_SA" \
  --build-service-account="projects/${PROJECT}/serviceAccounts/${BUILD_SA}" \
  \
  `# --- the free-tier envelope. Changing these is what costs money. ---` \
  --cpu=1 \
  --memory=512Mi \
  --min-instances=0 \
  --max-instances=3 \
  \
  `# Streamlit holds a WebSocket open for the life of the browser tab, and Cloud` \
  `# Run bills that as one long request. 3600s is the ceiling; past it the socket` \
  `# drops and Streamlit reconnects, which the user sees as a blink.` \
  --timeout=3600 \
  \
  `# Session state lives in the instance's memory. Without affinity a reconnect can` \
  `# land on a different instance and the conversation is gone.` \
  --session-affinity \
  --concurrency=80 \
  \
  `# Two keys, two secrets, and the Gemini one deliberately belongs to a DIFFERENT` \
  `# project -- one with no billing account, which is what Google uses to decide that` \
  `# a Gemini key is on the free tier. Minting a replacement inside this project would` \
  `# look tidier and would quietly move it to the paid tier. See profiles/rcc.toml.` \
  --set-secrets="OPENROUTER_API_KEY=${SECRET}:latest,GEMINI_API_KEY=${GEMINI_SECRET}:latest" \
  `# SAGE_DEFAULT_MODEL is what a fresh session STARTS on, and it is not implied by` \
  `# the profile's provider order -- app.py:81 reads this variable and only falls` \
  `# through to the first configured provider if it names nothing resolvable. Vertex` \
  `# was first in the lineup and still would not have answered a single turn, because` \
  `# the default resolved to openrouter/free and openrouter/free works. Failover order` \
  `# and the default are two separate decisions; this is the second one.` \
  --set-env-vars="SAGE_PROFILE=profiles/rcc.toml,SAGE_CALL_BUDGET=500,SAGE_VERTEX=1,SAGE_DEFAULT_MODEL=vertex:google/gemini-3.8-flash"

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
echo
echo "==> Live: ${URL}"
echo "    Logs:  gcloud run services logs tail ${SERVICE} --region=${REGION}"
