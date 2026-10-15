# Google Cloud Run (alternative to Fly.io)

Cloud Run scales to zero and out to N instances automatically; each instance here runs 2 workers.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT
gcloud run deploy uae-einvoice-check \
  --source . \
  --region me-central1 \            # Doha; or europe-west1
  --allow-unauthenticated \
  --cpu 2 --memory 1Gi \
  --concurrency 60 --min-instances 0 --max-instances 10 \
  --set-env-vars WEB_CONCURRENCY=2,HEAVY_CONCURRENCY=4,LEADS_DISABLED=0,DATA_DIR=/tmp/data
```

Leads on Cloud Run: the filesystem is ephemeral, so set `LEAD_WEBHOOK_URL` (a Google Sheets webhook via
Apps Script, n8n or Zapier) instead of relying on the JSONL file.
