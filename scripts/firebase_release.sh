#!/usr/bin/env bash
# Publish a Firebase Hosting release that routes https://uaeinvoicecheck.web.app/** to the Cloud Run service.
# Only needed when the rewrite config changes; Cloud Run deploys do not require a new release.
set -euo pipefail
P="${GCP_PROJECT:-e-invoicing-511716}"; SITE="${FIREBASE_SITE:-uaeinvoicecheck}"
TOKEN=$(gcloud auth print-access-token)
H=(-H "Authorization: Bearer ${TOKEN}" -H "x-goog-user-project: ${P}" -H "Content-Type: application/json")
API=https://firebasehosting.googleapis.com/v1beta1
V=$(curl -s "${H[@]}" -X POST "${API}/sites/${SITE}/versions" \
  -d '{"config":{"rewrites":[{"glob":"**","run":{"serviceId":"uae-einvoice-check","region":"me-central1"}}]}}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
curl -s "${H[@]}" -X PATCH "${API}/${V}?update_mask=status" -d '{"status":"FINALIZED"}' >/dev/null
curl -s "${H[@]}" -X POST "${API}/sites/${SITE}/releases?versionName=${V}" -d '{}' | python3 -c "import sys,json; print('released', json.load(sys.stdin)['name'])"
