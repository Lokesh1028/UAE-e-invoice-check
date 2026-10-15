# Deploy on Google Cloud Run (recommended)

Why: region `me-central1` (Doha) is closest to UAE users, Cloud Run load-balances and autoscales from 0 to N
instances on its own, HTTPS is included, and the monthly free tier (requests, vCPU-seconds, GiB-seconds per
billing account) covers launch-level traffic.

## One-time setup

1. Create a Google Cloud account and a billing account (a card is required even for the free tier).
2. Install the CLI and log in:

```bash
brew install --cask google-cloud-sdk
gcloud auth login
gcloud projects create uae-einvoice-check-prod --name="UAE e-invoice check"
gcloud config set project uae-einvoice-check-prod
gcloud billing projects link uae-einvoice-check-prod --billing-account=XXXXXX-XXXXXX-XXXXXX
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

3. Optional but recommended: a budget alert at e.g. USD 10 in Billing → Budgets & alerts.

## Deploy (run from the repository root)

```bash
gcloud run deploy uae-einvoice-check \
  --source . \
  --region me-central1 \
  --allow-unauthenticated \
  --cpu 2 --memory 1Gi \
  --concurrency 8 \
  --min-instances 0 --max-instances 20 \
  --cpu-boost \
  --timeout 90 \
  --set-env-vars WEB_CONCURRENCY=2,HEAVY_CONCURRENCY=2,HEAVY_QUEUE_WAIT_S=12,HEAVY_TIMEOUT_S=45,DATA_DIR=/tmp/data,APP_VERSION=0.2.5,BUILD_DATE=2026-10-15,PUBLIC_BASE_URL=https://uaeinvoicecheck.web.app,REDIRECT_TO_CANONICAL=0,GOOGLE_SITE_VERIFICATION=DeFElMnyjlhtqo5T0b9dYbSZO6xkwWttd2a6Syk9Hq8,GOOGLE_VERIFICATION_FILES=google7b55f293e02f9a93.html
```

* `--source .` builds the Dockerfile with Cloud Build; no local Docker needed.
* `--concurrency 8` makes Cloud Run add instances early instead of queueing inside one; tested with 100
  simultaneous uploaders (mix of 200-invoice CSVs, workbooks and XML): 997/997 succeeded in 30 s on 20 instances.
* `--max-instances 20` caps the worst-case bill. Raise it when traffic justifies it.
* First-time setup on a new project: if the build fails with PERMISSION_DENIED for the compute service account, run
  `gcloud projects add-iam-policy-binding PROJECT_ID --member=serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/run.builder`.
* Health check URL is `/health` (Cloud Run blocks paths ending in `z`, so `/healthz` only works inside the container).
* `--min-instances 0` costs nothing when idle; the first request after idle waits a few seconds.
  Set `--min-instances 1` during campaigns or demos to remove that wait (this is billed while idle).
* Re-run the same command to ship a new version. Cloud Run keeps old revisions for instant rollback:
  `gcloud run services update-traffic uae-einvoice-check --region me-central1 --to-revisions REVISION=100`.

## Leads

Every lead is written to Cloud Logging (kept 30 days by default):
`gcloud logging read 'textPayload:"INFO leads LEAD"' --freshness=30d --format='value(textPayload)'`.
The `leads.jsonl` file does not survive restarts on Cloud Run. For a live sheet, point
`LEAD_WEBHOOK_URL` at a Google Apps Script web app that appends rows to a Google Sheet, or at an n8n/Zapier
webhook, and redeploy with the URL filled in.

## Short address (Firebase Hosting, free)

`https://uaeinvoicecheck.web.app` is a Firebase Hosting site in the same project.

* **Crawlable pages are static files on Hosting**; everything else (API, tools, health) is rewritten to Cloud Run.
  Reason: through a pure Cloud Run rewrite, Googlebot requests that miss the Firebase/Fastly cache fail at the
  CDN ("robots.txt unreachable" / "URL is not available to Google"), while browsers and other crawlers work.
  Static files are served before rewrites, so Googlebot gets them. Verified with Google's Rich Results Test.
* **After every Cloud Run deploy that changes pages, republish the static site:**
  `./.venv/bin/python scripts/firebase_deploy.py` (renders every page with the app itself and uploads only changed files).
  Never publish a rewrite-only release; it would take the static pages away.
* Google verification files are deliberately NOT static (cleanUrls would 301 them); Cloud Run serves them.
* Firebase cuts rewrites at 60 s, hence `HEAVY_TIMEOUT_S=45` and `HEAVY_QUEUE_WAIT_S=12`.
* `REDIRECT_TO_CANONICAL` is OFF. When on, it sends human visitors of the long `*.run.app` address to the short one
  (302, no-store, crawlers never redirected). Canonical tags already point search engines at the short address.
* Request logs: Hosting's `cloudLoggingEnabled` is on; `scripts/visitors.py` reads them (log
  `firebasehosting.googleapis.com/webrequests`, includes client IP, city and country). Entries arrive in batches.

## Custom domain

Put Cloudflare in front (see `cloudflare.md`) and point a CNAME at the `*.run.app` hostname, or use
`gcloud beta run domain-mappings create --service uae-einvoice-check --domain check.example.com --region me-central1`.
