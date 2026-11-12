# CallPay

**An AI phone agent for local businesses.** It answers every call, takes the order from the real menu, texts a PayPal payment link, confirms the payment while the caller is still on the line, sends the order to the kitchen and pays the crew through PayPal Payouts. Every provider has an automatic fallback, so a call keeps going when a provider goes down.

> Built for the PayPal AI Hackathon 2026. PayPal **sandbox** only, no real money.

## The call-to-cash loop

```
Caller ──► Twilio / Telnyx / browser widget ──► Agent planner ──► Order-taker (menu DB prices only)
                                                       │
                                                       ▼
                     PayPal Orders checkout ──► SMS link (Twilio → Telnyx → on screen)
                                                       │
           PayPal webhook / capture ──► "Got your payment!" said on the same call
                                                       │
         Temporal workflow ──► kitchen ticket ──► ready text ──► crew payout (policy engine → PayPal Payouts)
                                                       │
                Kafka ──► Flink (revenue/min, fraud) ──► ClickHouse ──► dashboard + "Ask your business"
```

## What's in it

| Area | What it does | Fallback chain |
|---|---|---|
| Phone | Twilio / Telnyx webhooks with speech `<Gather>`; a hold loop confirms payment live | Browser call widget |
| Brain | Planner + sub-agents: Order-taker, Payments, Support, Payouts, Analyst | Claude → OpenAI → Gemini → Ollama (host GPU) → Ollama (Docker) → deterministic rules |
| Speech | Speech-to-text and text-to-speech | Deepgram → AssemblyAI → Whisper → browser · ElevenLabs → Cartesia → OpenAI → browser |
| Payments | PayPal Orders checkout, capture, refunds, disputes, Payouts, verified webhooks | Orders → Invoicing; payouts/refunds requeue for approval on failure |
| Workflows | call → paid → kitchen → ready → crew payout; unpaid → reminder text → expire | Temporal → in-process runner |
| Events | Every action is an event (`call.*`, `order.*`, `payment.*`, `payout.*`, `provider.*`) | Kafka → in-memory |
| Analytics | Flink SQL windows → ClickHouse (Kafka engine) → charts and the Analyst agent | ClickHouse → Postgres/SQLite |
| Storage | Call transcripts archived as JSON | SeaweedFS S3 → local disk |
| Data | Source of truth | Postgres → SQLite |
| Gateway | Rate limits, routing, `/internal` blocked | Kong → Caddy |
| Live call view | Overview streams active call turns, agent brain, and payment status | Recent call history restored from API |
| Payment QR | Scan-to-pay QR in the call and unpaid order views | Direct PayPal checkout URL |
| Recovery | Resend an unpaid order link with a two-minute cooldown | SMS provider or on-screen reminder |
| Order handling | Caller modifiers appear on tickets; optional 0/10/15/20% crew tips | Menu DB prices and code-computed totals only |
| Reliability view | Dashboard chart for measured chaos-run results | Does not simulate payments or report fake paid orders |
| Audit | Hash-chained records for money actions and provider controls, with verification UI | Local database storage |
| Deploy | Docker Compose; Helm chart for k3s (HPA, warm pool, PDB); Render blueprint | |

### Owner tools
- **Menu editor**: edit items and prices in an AG Grid; the agent sells from the new menu on the next call, and every change is audited.
- **PayPal reconciliation**: every paid order is matched to PayPal's Transaction Search report, with fees, net received, and anything missing or unexpected.
- **Fraud guard**: a number that calls too often is flagged; its checkout is capped, its refunds always need the owner, and hard per-caller limits apply to calls, checkouts and turns.
- **Owner alerts**: approvals, failed payouts, disputes, fraud flags and large orders reach the owner by text (Twilio → Telnyx) or on the dashboard.

### Safety rails
- **Money never comes from the AI.** Items and prices come from the menu table; the LLM only proposes intents, which are validated against the menu. Any reply that mentions a dollar amount that isn't a real price or total, or contains a URL, is replaced with a template.
- **Policy engine** for money leaving the business: payouts auto-send up to $50 and need owner approval above; hard limits deny ($500 per person, $1000 per batch, duplicate recipients). Refunds auto up to $20, never above the order total.
- **Idempotency keys** on every PayPal write (`PayPal-Request-Id` derived from our IDs), and deduplicated, signature-verified webhooks.
- **Prompt-injection screening** on everything a caller says; flagged turns are answered with the LLM told the text is untrusted.

## Run it

```bash
cp .env.example .env   # add your PayPal sandbox keys; everything else is optional
# Set INTERNAL_API_TOKEN to the same long random value for the API and Temporal worker.
docker compose up -d --build
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:8090 (via Kong) or http://localhost:3000 |
| Try a call (browser) | http://localhost:8090/call |
| API docs | http://localhost:8000/docs |
| Gateway fallback (Caddy) | http://localhost:8091 |
| Temporal UI | http://localhost:8088 |
| Flink UI | http://localhost:8082 |
| ClickHouse | http://localhost:8123 (callpay / callpay) |
| Grafana | http://localhost:3001 (admin / callpay) |

For a public URL (PayPal webhooks, Twilio): `powershell -File scripts\tunnel.ps1`, then set `APP_URL` in `.env`.

### Replit deployment
The repository includes a single-port Replit entrypoint for a Reserved VM. It runs Next.js publicly and keeps FastAPI private behind `/api`; use Replit PostgreSQL and add sandbox PayPal credentials in the published app's Secrets. Follow [docs/REPLIT_DEPLOYMENT.md](docs/REPLIT_DEPLOYMENT.md). The Replit app and its webhook still need to be published and verified by the owner.

### Tests
```bash
cd services/api
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # .venv/bin on macOS/Linux
.venv/Scripts/pytest -q
```
The suite runs a whole call end to end with every LLM switched off (the rules engine runs the call), plus Twilio TwiML, payouts, refunds, disputes and failover.

## Demo features

- **Live calls:** Overview streams transcript events and restores recent calls from the API.
- **Scan to pay:** the browser call and unpaid order views show a QR code for the PayPal checkout URL.
- **Link recovery:** Orders can resend an unpaid checkout link; the API rate-limits each order to one reminder per two minutes.
- **Order notes:** supported voice modifiers such as “no onions” are stored with the order and displayed to the kitchen without affecting price.
- **Crew tips:** the caller can choose 10%, 15%, 20%, or no tip. The server computes the tip from the database-priced food subtotal and includes it in PayPal checkout; all tip payouts still pass through the payout policy.
- **Item refunds:** owners can select line-item quantities; refund amounts are recomputed from stored order prices and checked by the refund policy.
- **Audit trail:** `/audit` and the Audit log page show hash-chained money and provider-control events; `/audit/verify` checks integrity.
- **Multilingual browser calls:** English, Hindi, Tamil, and Spanish can be selected. Speech APIs use the selected locale; model replies follow the language while item names still validate against the English menu. Deterministic fallback replies remain English.
- **Reliability view:** the Chaos runs page charts measured intake and failover results provided by the operator. It does not simulate checkout or paid events.

## Demo the failover
Open the dashboard Overview, start a call in another tab, and press **kill** on any provider in the Provider health panel. The next turn runs on the next provider; the event feed shows the failover.

```bash
curl -X POST localhost:8000/providers/llm/ollama/kill
curl -X POST localhost:8000/providers/payments/orders/kill   # next checkout falls back to a PayPal Invoice
curl localhost:8000/providers
```

## Docs
- [docs/JUDGE_GUIDE.md](docs/JUDGE_GUIDE.md): how to try it in 2 minutes
- [docs/callpay.postman_collection.json](docs/callpay.postman_collection.json): every endpoint
- [infra/helm/callpay](infra/helm/callpay): k3s deployment

## License
MIT
