# Render deployment (free plan)

The root `Dockerfile` packs the API, the dashboard and a small gateway into one container, so Render serves everything on one URL: pages at `/`, the API at `/api`. `render.yaml` describes that service plus a free Postgres database.

## Deploy

1. Push `main` to GitHub.
2. In Render: **New → Blueprint**, connect the GitHub repository, pick `main`. Render reads `render.yaml`.
3. Fill in the values it asks for:

   | Variable | Value |
   |---|---|
   | `PAYPAL_CLIENT_ID` | Sandbox app client ID |
   | `PAYPAL_CLIENT_SECRET` | Sandbox app secret |
   | `CREW_EMAILS` | Comma-separated sandbox personal emails for crew payouts |
   | `PAYPAL_WEBHOOK_ID` | Leave empty for now (step 5) |
   | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | Optional; leave empty to use the rules engine |

4. Apply. The first build takes several minutes. When it is live, open `https://<name>.onrender.com/api/health`; expect `database: postgres` and `paypal_configured: true`.
5. In the PayPal sandbox app add a webhook for `https://<name>.onrender.com/api/webhooks/paypal` (all events), copy its ID into `PAYPAL_WEBHOOK_ID` in the service's Environment tab, and save (Render redeploys).
6. Place a test order on `/call`, pay with a sandbox buyer, and check the agent confirms the payment.

## Good to know

- **The free plan sleeps after about 15 minutes without traffic**, and the next visit takes up to a minute to wake it. Open the site shortly before a demo, or point a free uptime monitor at `/api/health`. An order waiting for payment when the service sleeps loses its in-memory timer; the payment itself is still captured when the buyer returns.
- `APP_URL` is derived from Render's `RENDER_EXTERNAL_URL`. Set it yourself only for a custom domain (`https://your.domain/api`).
- Memory: the Nov 12 Render-shaped smoke used 266.5 MiB under a hard 512 MiB container cap after loading the dashboard and making a call turn; usage can vary with traffic and provider configuration.
- Free Postgres databases on Render expire after a limited time; fine for judging, not for long-term use.
- Verified locally on Nov 12 with the fixed image under a 512 MiB limit and `PORT=10000`: Next.js and the API started without installing runtime dependencies, the gateway bound the assigned port, all dashboard pages and API health/audit endpoints returned 200, internal routes returned 403, SSE streamed, and a call turn returned the code-computed menu total. PayPal credentials were intentionally absent in this smoke, so checkout creation, capture, webhook delivery, in-call confirmation, and payout remain unverified on this image and on Render itself.
