#!/usr/bin/env bash
# Route Sage's records from Cloud Logging into BigQuery, and count them as they arrive.
#
# Idempotent: safe to re-run. Every resource is looked up before it is made, and a
# re-run brings the sink's filter and each metric's definition back to what this file
# says, so editing a metric here and running it again is how a metric changes.
#
#   ./deploy/observability.sh                   # dataset, sink, grant, metrics
#   ./deploy/observability.sh --openrouter-sa   # and the identity OpenRouter writes as
#
# What it reads: the records the app prints to stdout when SAGE_TELEMETRY=stdout, which
# deploy/cloudrun.sh sets. One JSON line per turn, model call, miss and rating; Cloud
# Run ships them to Cloud Logging as structured entries, and nothing here touches the
# app. See deploy/README.md, "Observability", for what to do with them.
#
# Run by hand with an owner's credentials. The deploy identity cannot run this, on
# purpose: it holds no rights over BigQuery, log sinks, metrics or service accounts,
# for the same reason cloudrun.sh's one-time block is skipped in CI.
set -euo pipefail

PROJECT="$(gcloud config get-value project 2>/dev/null)"
SERVICE="${SERVICE:-sage}"
# The same region as cloudrun.sh. BigQuery calls it a location; the records stay in the
# region the service writes them from.
REGION="${REGION:-us-central1}"
BQ_LOCATION="${BQ_LOCATION:-$REGION}"
DATASET="${DATASET:-sage_obs}"
SINK="${SINK:-sage-obs}"
BROADCAST_NAME="${BROADCAST_NAME:-sage-openrouter-broadcast}"
# 90 days, in seconds. A dataset default, so every partitioned table the sink makes
# (and the one OpenRouter writes, if it is partitioned) drops a day's partition 90 days
# after it was written: the dataset cannot grow without bound, and nothing older than
# a quarter is kept about anyone's questions.
EXPIRATION=$((90 * 24 * 60 * 60))

OPENROUTER_SA=0
for arg in "$@"; do
  case "$arg" in
    --openrouter-sa) OPENROUTER_SA=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  echo "No project set. Run: gcloud config set project <PROJECT_ID>" >&2
  exit 1
fi

bq_() { bq --headless --project_id="$PROJECT" "$@"; }

# Temporary files, removed however the script ends. A failed `bq update` under `set -e`
# leaves before any line after it runs, and would leave a copy of the dataset's access
# list behind with it.
TEMPS=()
cleanup() { if [[ ${#TEMPS[@]} -gt 0 ]]; then rm -f -- "${TEMPS[@]}"; fi; }
trap cleanup EXIT

echo "==> Project ${PROJECT}, service ${SERVICE}, dataset ${DATASET} in ${BQ_LOCATION}"

# Both are no-ops when already on. BigQuery is not on by default in a new project, and
# without it the dataset below fails with an error about permissions rather than APIs.
gcloud services enable bigquery.googleapis.com logging.googleapis.com

# ---------------------------------------------------------------- the dataset
if bq_ show "${PROJECT}:${DATASET}" >/dev/null 2>&1; then
  echo "==> Dataset ${DATASET} exists; holding its partition expiration at 90 days"
  bq_ update --default_partition_expiration="$EXPIRATION" "${PROJECT}:${DATASET}" >/dev/null
else
  echo "==> Creating dataset ${DATASET}"
  bq_ mk --dataset --location="$BQ_LOCATION" \
    --default_partition_expiration="$EXPIRATION" \
    --description="Sage turn, call, miss and rating records, routed from Cloud Logging" \
    "${PROJECT}:${DATASET}"
fi

# Data Editor on THIS dataset, and nowhere else. A dataset's grants live in its access
# list, which is edited by round-tripping it through `bq show` and `bq update`: `bq
# add-iam-policy-binding` only fully supports tables and views. WRITER is that list's
# name for roles/bigquery.dataEditor.
grant_writer() {
  local email="$1" spec verdict=0
  spec="$(mktemp)"
  TEMPS+=("$spec")
  bq_ show --format=prettyjson "${PROJECT}:${DATASET}" > "$spec"
  python3 - "$spec" "$email" <<'PY' || verdict=$?
import json
import sys

path, email = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    dataset = json.load(handle)
access = dataset.setdefault("access", [])
if any(
    entry.get("userByEmail") == email
    and entry.get("role") in ("WRITER", "roles/bigquery.dataEditor")
    for entry in access
):
    sys.exit(3)
access.append({"role": "WRITER", "userByEmail": email})
with open(path, "w", encoding="utf-8") as handle:
    json.dump(dataset, handle)
PY
  case "$verdict" in
    0) bq_ update --source "$spec" "${PROJECT}:${DATASET}" >/dev/null
       echo "    ${email}: BigQuery Data Editor on ${DATASET}" ;;
    3) echo "    ${email} already has Data Editor on ${DATASET}" ;;
    *) echo "Could not read the access list of ${DATASET}" >&2
       exit 1 ;;
  esac
}

# ------------------------------------------------------------------- the sink
# The service's stdout, and of that only the four kinds of record. Everything else the
# container prints (Streamlit's own lines, Python's warnings) is text, not one of these,
# and stays in Cloud Logging alone. Partitioned tables, so the 90 days above apply and
# a query can name the days it needs instead of scanning every row.
STDOUT_LOG="projects/${PROJECT}/logs/run.googleapis.com%2Fstdout"
FROM_SERVICE="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE}\" AND logName=\"${STDOUT_LOG}\""
LOG_FILTER="${FROM_SERVICE} AND (jsonPayload.kind=\"turn\" OR jsonPayload.kind=\"call\" OR jsonPayload.kind=\"miss\" OR jsonPayload.kind=\"rating\")"
DESTINATION="bigquery.googleapis.com/projects/${PROJECT}/datasets/${DATASET}"

if gcloud logging sinks describe "$SINK" >/dev/null 2>&1; then
  echo "==> Sink ${SINK} exists; setting its destination and filter"
  gcloud logging sinks update "$SINK" "$DESTINATION" \
    --log-filter="$LOG_FILTER" --use-partitioned-tables \
    --description="Sage records (turn, call, miss, rating) into ${DATASET}" >/dev/null
else
  echo "==> Creating sink ${SINK}"
  gcloud logging sinks create "$SINK" "$DESTINATION" \
    --log-filter="$LOG_FILTER" --use-partitioned-tables \
    --description="Sage records (turn, call, miss, rating) into ${DATASET}" >/dev/null
fi

# The sink writes as an identity of its own, which can write nowhere until it is
# granted: entries routed before this line runs are dropped, not queued.
WRITER="$(gcloud logging sinks describe "$SINK" --format='value(writerIdentity)')"
if [[ -z "$WRITER" ]]; then
  echo "Sink ${SINK} reports no writer identity, so nothing can be granted to it" >&2
  exit 1
fi
grant_writer "${WRITER#serviceAccount:}"

# ---------------------------------------------------------------- the metrics
# Counted by Cloud Logging as entries arrive, so a chart of them costs no query. Each
# definition is written to a temporary file because labels and distributions can only
# be declared through --config-from-file. YAML with single-quoted strings, so the
# filter's double quotes need no escaping.
metric() {
  local name="$1" config
  config="$(mktemp)"
  TEMPS+=("$config")
  cat > "$config"
  if gcloud logging metrics describe "$name" >/dev/null 2>&1; then
    gcloud logging metrics update "$name" --config-from-file="$config" >/dev/null
    echo "    updated ${name}"
  else
    gcloud logging metrics create "$name" --config-from-file="$config" >/dev/null
    echo "    created ${name}"
  fi
}

echo "==> Log-based metrics"

metric sage_turns <<YAML
description: Sage turns, by how they ended.
filter: '${FROM_SERVICE} AND jsonPayload.kind="turn"'
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
  unit: '1'
  labels:
  - key: outcome
    valueType: STRING
    description: answered or failed
labelExtractors:
  outcome: EXTRACT(jsonPayload.outcome)
YAML

metric sage_failed_calls <<YAML
description: Sage model calls that failed, by provider and the kind of failure.
filter: '${FROM_SERVICE} AND jsonPayload.kind="call" AND jsonPayload.ok=false'
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
  unit: '1'
  labels:
  - key: provider
    valueType: STRING
    description: the profile's name for the provider asked
  - key: error_kind
    valueType: STRING
    description: llm.classify's kind, where empty also covers a stream the app refused to ship
labelExtractors:
  provider: EXTRACT(jsonPayload.provider)
  error_kind: EXTRACT(jsonPayload.error_kind)
YAML

metric sage_turn_seconds <<YAML
description: How long a Sage turn took, from its first request to its end, failovers included.
filter: '${FROM_SERVICE} AND jsonPayload.kind="turn"'
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: s
  labels:
  - key: outcome
    valueType: STRING
    description: answered or failed
valueExtractor: EXTRACT(jsonPayload.seconds)
labelExtractors:
  outcome: EXTRACT(jsonPayload.outcome)
bucketOptions:
  exponentialBuckets:
    numFiniteBuckets: 16
    growthFactor: 1.6
    scale: 0.5
YAML

# Two metrics rather than one, because a log entry gives a distribution one value. Only
# calls whose endpoint reported usage: a null count is unknown, not zero.
for direction in in out; do
  metric "sage_tokens_${direction}" <<YAML
description: Tokens ${direction} per Sage model call, by provider, where the endpoint reported usage.
filter: '${FROM_SERVICE} AND jsonPayload.kind="call" AND jsonPayload.tokens_${direction}>=0'
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: '1'
  labels:
  - key: provider
    valueType: STRING
    description: the profile's name for the provider asked
valueExtractor: EXTRACT(jsonPayload.tokens_${direction})
labelExtractors:
  provider: EXTRACT(jsonPayload.provider)
bucketOptions:
  exponentialBuckets:
    numFiniteBuckets: 18
    growthFactor: 2
    scale: 10
YAML
done

# ------------------------------------------------- OpenRouter's Broadcast, opt-in
if [[ "$OPENROUTER_SA" == "1" ]]; then
  BROADCAST_SA="${BROADCAST_NAME}@${PROJECT}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$BROADCAST_SA" >/dev/null 2>&1; then
    echo "==> Creating service account ${BROADCAST_SA}"
    gcloud iam service-accounts create "$BROADCAST_NAME" \
      --display-name="OpenRouter Broadcast into ${DATASET}"
    # IAM is eventually consistent, and a dataset's access list refuses an account it
    # cannot see yet. The same cheap insurance cloudrun.sh takes after its bindings.
    sleep 10
  fi
  # Data Editor on the dataset and nothing more. NOT BigQuery Job User: OpenRouter's
  # BigQuery destination uses streaming inserts, which need no job rights, and its own
  # setup guide says not to grant it.
  grant_writer "$BROADCAST_SA"

  # The key is the one step left to a person, deliberately. A JSON key is a long-lived
  # bearer credential that leaves this project the moment it is pasted elsewhere, so
  # whether to mint one is a decision this script does not make.
  cat <<OUT

The account exists and can write to ${DATASET} and nowhere else. What is left is by
hand, in this order:

  1. Create a JSON key for it, and keep it out of the repository:
       \$ gcloud iam service-accounts keys create broadcast-key.json \\
           --iam-account=${BROADCAST_SA}
  2. In OpenRouter, Settings > Observability, add a Google BigQuery destination and
     paste the whole key file. Then delete the local copy of the key.
  3. Open "View Setup Instructions" on that destination and run its CREATE TABLE in
     the BigQuery console, with \`my-gcp-project\` replaced by ${PROJECT} and the
     dataset by ${DATASET}.
  4. Turn on Privacy Mode for the destination, so prompts and completions are stripped
     and only tokens, cost, timing and metadata (the session and trace ids) arrive.
  5. Give each deployment its own OpenRouter API key, and limit this destination to the
     Cloud Run deployment's key, so a laptop's or another host's traffic never lands in
     the same table.

OUT
fi

# Measured on the first run, 2026-10-06: a record written 49 s after the grant never
# arrived (the grant had not taken effect, and the sink drops what it cannot write),
# and the next question's rows took about five minutes to appear in the new table.
echo "==> Done. On a first run the grant can take a few minutes to take effect, and records"
echo "    written before then stay in Cloud Logging only. After that, records reach"
echo "    ${PROJECT}:${DATASET} within a few minutes of being written."
