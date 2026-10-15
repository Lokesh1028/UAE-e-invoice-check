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
  --concurrency 20 \
  --min-instances 0 --max-instances 10 \
  --timeout 90 \
  --set-env-vars WEB_CONCURRENCY=2,HEAVY_CONCURRENCY=2,DATA_DIR=/tmp/data,LEAD_WEBHOOK_URL=
```

* `--source .` builds the Dockerfile with Cloud Build; no local Docker needed.
* `--max-instances 10` caps the worst-case bill. Raise it when traffic justifies it.
* `--min-instances 0` costs nothing when idle; the first request after idle waits a few seconds.
  Set `--min-instances 1` during campaigns or demos to remove that wait (this is billed while idle).
* Re-run the same command to ship a new version. Cloud Run keeps old revisions for instant rollback:
  `gcloud run services update-traffic uae-einvoice-check --region me-central1 --to-revisions REVISION=100`.

## Leads

The Cloud Run filesystem is ephemeral, so the `leads.jsonl` file does not survive restarts. Point
`LEAD_WEBHOOK_URL` at a Google Apps Script web app that appends rows to a Google Sheet, or at an n8n/Zapier
webhook, and redeploy with the URL filled in.

## Custom domain

Put Cloudflare in front (see `cloudflare.md`) and point a CNAME at the `*.run.app` hostname, or use
`gcloud beta run domain-mappings create --service uae-einvoice-check --domain check.example.com --region me-central1`.
