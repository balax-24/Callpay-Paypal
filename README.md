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
| Deploy | Docker Compose; Helm chart for k3s (HPA, warm pool, PDB); Render blueprint | |

### Safety rails
- **Money never comes from the AI.** Items and prices come from the menu table; the LLM only proposes intents, which are validated against the menu. Any reply that mentions a dollar amount that isn't a real price or total, or contains a URL, is replaced with a template.
- **Policy engine** for money leaving the business: payouts auto-send up to $50 and need owner approval above; hard limits deny ($500 per person, $1000 per batch, duplicate recipients). Refunds auto up to $20, never above the order total.
- **Idempotency keys** on every PayPal write (`PayPal-Request-Id` derived from our IDs), and deduplicated, signature-verified webhooks.
- **Prompt-injection screening** on everything a caller says; flagged turns are answered with the LLM told the text is untrusted.

## Run it

```bash
cp .env.example .env   # add your PayPal sandbox keys; everything else is optional
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

### Tests
```bash
cd services/api
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # .venv/bin on macOS/Linux
.venv/Scripts/pytest -q
```
The suite runs a whole call end to end with every LLM switched off (the rules engine runs the call), plus Twilio TwiML, payouts, refunds, disputes and failover.

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
