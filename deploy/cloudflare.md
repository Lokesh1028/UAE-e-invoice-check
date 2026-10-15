# Put Cloudflare in front (free plan)

1. Add your domain to Cloudflare, point `check.yourdomain.com` (CNAME) at the Fly/Cloud Run hostname, proxy ON (orange cloud).
2. SSL/TLS mode: Full (strict).
3. Caching → Cache Rules: cache `/static/*` for 1 day. Do not cache `/api/*`.
4. Security → WAF → Rate limiting rule (free tier allows one):
   - If URI path starts with `/api/` and method is POST → 30 requests per 1 minute per IP → Block for 1 minute.
5. Security → Bots: enable "Bot fight mode".
6. Optional: Turnstile on the lead form if spam appears.

When Cloudflare is in front of Cloud Run, redeploy with `XFF_TRUSTED_HOPS=2` so the app's own rate limiter
reads the visitor's IP (Cloudflare appends it, then Cloud Run appends Cloudflare's edge IP). Without Cloudflare keep the default of 1.
