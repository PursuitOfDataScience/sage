#!/usr/bin/env bash
# Let GitHub Actions deploy to Cloud Run WITHOUT a service-account key.
#
# The obvious way to do this is to mint a JSON key for a deployer account and paste
# it into a GitHub secret. Don't: that key is a permanent bearer credential sitting
# in a third party's database, it does not expire, and rotating it is a manual chore
# nobody does. Workload Identity Federation instead has GitHub mint a short-lived
# OIDC token per run, which Google exchanges for a ~1 hour access token. Nothing
# long-lived exists to leak.
#
# Idempotent. Run once per project.
set -euo pipefail

PROJECT="$(gcloud config get-value project)"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
REPO="${REPO:-PursuitOfDataScience/sage}"
OWNER="${REPO%%/*}"
POOL="${POOL:-github}"
PROVIDER="${PROVIDER:-github}"
DEPLOYER="${DEPLOYER:-sage-deployer}"
SA="${DEPLOYER}@${PROJECT}.iam.gserviceaccount.com"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-sage}"

gcloud services enable iamcredentials.googleapis.com sts.googleapis.com >/dev/null

# --- the pool and the GitHub provider ---------------------------------------
if ! gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL" --location=global \
    --display-name="GitHub Actions"
fi

# The attribute-condition is the security boundary and is NOT optional. Without it
# any repository on GitHub can present a token to this provider and impersonate the
# deployer. Google now refuses to create the provider without one, which is the right
# default arriving late.
if ! gcloud iam workload-identity-pools providers describe "$PROVIDER" \
      --location=global --workload-identity-pool="$POOL" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --location=global --workload-identity-pool="$POOL" \
    --display-name="GitHub" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository_owner=='${OWNER}'"
fi

# --- the deployer identity ---------------------------------------------------
if ! gcloud iam service-accounts describe "$SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$DEPLOYER" --display-name="GitHub Actions deployer"
fi

# Deploy revisions, submit builds, push images. Not editor, not owner.
for ROLE in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${SA}" --role="$ROLE" --condition=None >/dev/null
done

# `gcloud run deploy --source` uploads a zip to this bucket. Scoped to the one bucket
# rather than granted project-wide, which is what Google's own guide tells you to do.
BUCKET="gs://run-sources-${PROJECT}-${REGION}"
if gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets add-iam-policy-binding "$BUCKET" \
    --member="serviceAccount:${SA}" --role=roles/storage.objectAdmin >/dev/null
fi

# Deploying a service that RUNS AS sage-run means acting as sage-run. Same for the
# build account. Granted per-account, not project-wide: the deployer may impersonate
# exactly these two and nothing else.
for TARGET in "${SERVICE}-run" "${SERVICE}-build"; do
  gcloud iam service-accounts add-iam-policy-binding \
    "${TARGET}@${PROJECT}.iam.gserviceaccount.com" \
    --member="serviceAccount:${SA}" --role=roles/iam.serviceAccountUser >/dev/null
done

# --- let ONLY this repository impersonate the deployer -----------------------
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" >/dev/null

cat <<OUT

Done. Put these in .github/workflows/deploy.yml:

  workload_identity_provider: projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}
  service_account:            ${SA}

Neither is a secret -- they are identifiers, and the attribute condition above is
what stops anyone else using them.
OUT
