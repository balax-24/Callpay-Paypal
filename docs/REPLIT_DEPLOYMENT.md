# Replit deployment

CallPay's Docker Compose stack is designed for local development. The Replit entrypoint runs the FastAPI API, Next.js dashboard, and a small streaming HTTP gateway on one Reserved VM; optional Kafka, Temporal, ClickHouse, Redis, and S3 services fall back to the API's local/in-memory alternatives. Use Replit PostgreSQL for durable order and payout records.

## Publish

1. Import the GitHub repository into Replit. Keep this project's `main` branch as the source of truth; do not use Replit Agent to rewrite the app.
2. Add a Replit SQL database and use its production `DATABASE_URL` for the published app.
3. Choose a **Reserved VM** deployment. The project exposes the streaming gateway on internal port `3000`; the Replit config maps that to public port `80`. The API stays on loopback port `8000`, Next.js stays on loopback port `3001`, and the gateway streams `/api/*` to FastAPI while proxying other paths to Next.js.
4. Add the following to the published app's Secrets (not to Git):

   | Secret | Value |
   |---|---|
   | `DATABASE_URL` | Replit production PostgreSQL connection URL |
   | `PAYPAL_ENV` | `sandbox` |
   | `PAYPAL_CLIENT_ID` | Sandbox app client ID |
   | `PAYPAL_CLIENT_SECRET` | Sandbox app secret |
   | `PAYPAL_WEBHOOK_ID` | Webhook ID registered for the published URL |
   | `CREW_EMAILS` | Optional comma-separated sandbox crew recipient emails |

   Optional LLM, speech, or SMS keys can be added later. The core browser-order flow uses the deterministic rules fallback when no LLM key is configured. Do not add production PayPal credentials for the hackathon demo.

5. Publish once to receive the Replit URL. Set the published app's `APP_URL` secret to `https://<your-app>.replit.app/api`, then republish. This is the base used to build PayPal return URLs.
6. In the PayPal sandbox app, register `https://<your-app>.replit.app/api/webhooks/paypal` for the required events and update `PAYPAL_WEBHOOK_ID` in Replit Secrets. Republish after changing the secret.
7. Verify `https://<your-app>.replit.app/api/health` reports `database: postgres` and `paypal_configured: true`; exercise `/call`, `/orders`, `/payouts`, and the approved sandbox checkout before sharing the URL.

## Runtime notes

- Reserved VM is selected because the fallback order workflow and live event stream need a continuously running process. Autoscale can scale to zero and is not the chosen deployment for this configuration.
- Replit's production app needs only one public port. `/api/*` is an internal Next.js rewrite, so no API port is exposed.
- The full Kafka/Flink/ClickHouse/Temporal observability stack remains available through Docker Compose locally; this one-VM deployment uses the app's documented fallback paths.
- The public Replit URL, production database, PayPal webhook registration, and end-to-end Replit payment must be verified by the owner after publishing. This guide does not claim a Replit deployment has already been created.
