# Deploying Sage to Cloud Run

`cloudrun.sh` does everything that can be scripted. What is left here is the part
that needs a browser and a human.

## One-time, in a browser

1. **Create the account** at <https://cloud.google.com/free>. A credit card is
   required for identity verification. The trial does **not** auto-charge: when the
   $300 or the 90 days run out, resources stop and the account waits for you to
   manually upgrade.
2. **Create a project** and note its ID (not its display name).

## One-time, in a shell

**Already done on this cluster.** The SDK (584.0.0) is installed at
`/project/rcc/youzhi/google-cloud-sdk`, outside the repo and in project space rather
than a home directory. All it needs is the PATH:

```bash
export PATH="/project/rcc/youzhi/google-cloud-sdk/bin:$PATH"
```

Worth adding to `~/.bashrc`. It needs no root and no conda env: 584 bundles its own
Python 3.14, so `gcloud` works from a bare shell.

<details><summary>How it was installed, and the one thing that goes wrong</summary>

The documented one-liner half-fails here. The tarball extracts, then the bootstrap
step raises `SyntaxError: invalid syntax` on a walrus operator, because it runs under
whatever `python` is first on PATH — on these login nodes that is 3.6. The fix is to
point the installer at a modern interpreter and re-run the post-install step, which
is idempotent:

```bash
cd /project/rcc/youzhi
curl -sSL https://sdk.cloud.google.com -o /tmp/gcloud-install.sh
bash /tmp/gcloud-install.sh --install-dir=/project/rcc/youzhi --disable-prompts   # SyntaxError here is expected
source /software/python-miniforge-25.3.0-el8-x86_64/bin/activate AI
CLOUDSDK_PYTHON="$(command -v python)" /project/rcc/youzhi/google-cloud-sdk/install.sh \
  --quiet --usage-reporting=false --path-update=false --command-completion=false
```

`CLOUDSDK_PYTHON` is only needed for that one command; the installed `gcloud` uses
its bundled interpreter afterwards.

</details>

Then authenticate. `gcloud auth login` wants a browser; on a headless node use the
no-browser flow, which prints a URL to open anywhere and a code to paste back:

```bash
gcloud auth login --no-launch-browser
gcloud config set project <PROJECT_ID>
```

## Every deploy

```bash
cd /project/rcc/youzhi/sage
./deploy/cloudrun.sh
```

First run enables five APIs, prompts once for the OpenRouter key — which it puts in
Secret Manager, so the key never enters the repo, the image, or a shell history file —
and creates `sage-run@<project>.iam.gserviceaccount.com` for the service to run as.
That takes a couple of minutes. Later runs are build-and-deploy only, about 90 seconds.

The service account is worth understanding rather than skipping past, because the
default is a trap: Cloud Run otherwise runs as the project's compute service account,
which carries **roles/editor on the entire project**. Sage is a public URL that feeds
reader-supplied text to a model and runs a tool loop on the result, so an identity
that can delete the project's buckets is the wrong one to hand it. `sage-run` holds
one permission — read one secret — and that is the whole of what the app needs.

## Staying inside the free tier

The Always Free grant has three axes, and the one that binds is not the one you would
watch. Compute is 180,000 vCPU-seconds and 360,000 GiB-seconds a month; at
`--cpu=1 --memory=512Mi` that is 180,000 instance-seconds — about **50 hours a month**,
against 200 hours of the memory grant. But egress is **1 GB from North America**, and
measured against the deployed service one cold visit plus one question moves **3.64 MB**:
3.29 MB of it Streamlit's own JS bundle over 104 requests, and 0.03 MB the question and
the answer. That is **~295 first-time visitors a month**, against roughly 600 five-minute
visits' worth of compute — so egress runs out about twice as fast as the thing everyone
sizes for.

The caveat cuts the other way and is larger: those 3.29 MB are static assets the browser
caches, so a reader who comes back costs ~0.03 MB a question. 295 is the all-strangers
worst case, not the steady state. And egress past the grant is about $0.12/GB, so ten
times over the line is roughly a dollar.

Two things decide how far that goes, and they pull opposite ways. Streamlit holds a
WebSocket open for as long as the browser tab is, and Cloud Run counts an instance as
billable for as long as it is handling at least one request — so an idle tab someone
forgot to close bills exactly like one being read. But billing is per INSTANCE, not
per request, and `--concurrency=80` puts up to eighty of those tabs on one instance:
ten readers for an hour costs an hour, not ten. So the budget is ~50 hours a month of
*somebody* having it open — around 1.6 hours a day — however many somebodies there are.

That is comfortable for a demo link and tight for a service people leave open all day:
one reader with a tab open during work hours is ~56 hours and over the line on their
own. Going over is not a cliff — the overage rate works out near **$4–5 for another 50
hours** — but it is the number to watch, and the way to watch it is a budget alert.

The settings in `cloudrun.sh` that keep it there:

| flag | why |
| --- | --- |
| `--min-instances=0` | An always-warm instance is ~2.6M vCPU-s/month, 14× the grant. Costs a 5–15s cold start. |
| `--max-instances=3` | The default is 100. One crawler on a public URL is otherwise an unbounded bill. |
| `--cpu=1 --memory=512Mi` | The corpus is 341 KB, so memory is Streamlit's baseline, not Sage's index. |
| `SAGE_CALL_BUDGET=500` | Sage's own per-window cap on provider calls — a second, app-level brake. |

Also worth doing once, in the console: a **budget alert at $1**. Note that budget
alerts only notify; the things that actually bound spend are `max-instances` and the
trial account not auto-upgrading.

Artifact Registry's free storage is **0.5 GB**. Measured rather than estimated: the
image is **221 MB**, so exactly two fit and a third does not. A cleanup policy is
applied on the deployed project and should be applied on any new one — `keep` the two
most recent versions, `delete` anything else over a day old, with keep taking
precedence so a fresh deploy is never the thing that gets collected:

```bash
gcloud artifacts repositories set-cleanup-policies cloud-run-source-deploy \
  --location=us-central1 --policy=deploy/cleanup-policy.json
```

Without it every deploy adds 221 MB and the repository is over the free tier on the
third one. This is the only part of the setup that bills while nobody is using the app.

## Teardown

Deleting the service stops the compute, which is the part that bills by the second.
Three other things outlive it, and the Artifact Registry images are the ones that go
on costing (0.5 GB free, ~400 MB an image):

```bash
gcloud run services delete sage --region=us-central1
gcloud artifacts repositories delete cloud-run-source-deploy --location=us-central1
gcloud secrets delete sage-openrouter-key
gcloud iam service-accounts delete sage-run@<PROJECT_ID>.iam.gserviceaccount.com
```

Or delete the whole project (`gcloud projects delete <PROJECT_ID>`), which is the only
way to be sure nothing is left running — and the reason to give this deployment a
project of its own rather than sharing one.
