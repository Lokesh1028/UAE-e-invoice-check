# Put Cloudflare in front (free plan)

1. Add your domain to Cloudflare, point `check.yourdomain.com` (CNAME) at the Fly/Cloud Run hostname, proxy ON (orange cloud).
2. SSL/TLS mode: Full (strict).
3. Caching → Cache Rules: cache `/static/*` for 1 day. Do not cache `/api/*`.
4. Security → WAF → Rate limiting rule (free tier allows one):
   - If URI path starts with `/api/` and method is POST → 30 requests per 1 minute per IP → Block for 1 minute.
5. Security → Bots: enable "Bot fight mode".
6. Optional: Turnstile on the lead form if spam appears.

The app finds the visitor IP by walking X-Forwarded-For from the right past known proxy ranges (Google front end and
Google services, Fastly/Firebase, Cloudflare; see `app/resources/trusted_proxies.json`), so no setting is needed
when Cloudflare is added in front.
