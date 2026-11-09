# CallPay — Agent Handoff (Nov 9, 2026)

Read this first, then `README.md`. Older planning notes live one folder up: `D:\Projects\Paypal\RESUME.md`, `MASTER_PLAN.md`, `ARCHITECTURE.md`.

> **DEADLINE FIRST.** The PayPal AI Hackathon (Devpost, paypalaihackathon.devpost.com) closes about **Nov 12, 2026**. Check the exact time and timezone in the Official Rules today. Submission (section 3, P0) beats every new feature. Submit at least 6 hours early.

---

## 1. Rules for whoever continues

- **Sole author.** The owner is the only contributor. Commit as `Balaharish Saravanan <balaharish0202@gmail.com>` (already set in this repo's git config). **Never add `Co-Authored-By` or any AI attribution** to commits, PRs, README or the Devpost text.
- **Small commits, one per stage** (`feat(...)`, `fix(...)`, `docs:` style). Normal pushes only, **never force-push** `main`.
- **Never paste secrets into chat or commits.** Keys live only in `callpay/.env` (git-ignored). The PayPal sandbox app is **"CallPay US"** (US business `sb-guxbp53788085@business.example.com`).
- Don't type passwords into websites. Paying as the sandbox buyer is done by the owner.
- Run tests before every commit: `cd services/api && .venv/Scripts/python -m pytest -q` (28 should pass), plus `cd apps/web && npm run lint && npm run build`.

## 2. What works today (verified live on Nov 8–9)

Full loop with a real sandbox payment: browser call → agent builds the cart from the menu DB → PayPal Orders checkout link → buyer pays → capture + 2 signature-verified webhooks → **agent says "got your payment" on the call** → Temporal workflow: kitchen → ready → **automatic crew payout via PayPal Payouts** (policy engine: auto ≤ $50, owner approval above).

Also working: refunds (auto ≤ $20, approval above), dispute evidence drafted from the transcript, Kafka → Flink (job `callpay-analytics` RUNNING) → ClickHouse, "Ask your business" analyst, Next.js + AG Grid dashboard with live provider kill/revive, object storage for transcripts, Grafana dashboard, Helm chart (lints), Render blueprint, CI (api/web/compose/helm green after the last fix).

**Fallback chains** (every layer degrades instead of failing): LLM Claude→OpenAI→Gemini→Ollama(host)→Ollama(Docker)→rules engine · STT Deepgram→AssemblyAI→Whisper→browser · TTS ElevenLabs→Cartesia→OpenAI→browser · SMS Twilio→Telnyx→on screen · payments Orders→Invoicing · workflows Temporal→in-process · events Kafka→memory · analytics ClickHouse→Postgres · DB Postgres→SQLite · storage S3→disk · gateway Kong→Caddy.

## 3. Remaining work, in priority order

### P0 — needed to submit (do these first)
1. **Make the GitHub repo public** (`balax-24/Paypal_Hackathon`; MIT license already in place). Owner does this in GitHub settings.
2. **Public demo URL.** Option A: deploy with `render.yaml` (API + web + Postgres; set `APP_URL`, `NEXT_PUBLIC_API_URL`, PayPal keys in Render). Option B: keep the Cloudflare quick tunnel (`scripts/tunnel.ps1`), but **its URL changes on every restart**, so then update `APP_URL` in `.env` and the PayPal webhook URL (developer.paypal.com → CallPay US → Webhooks), and restart the API. For judging, Render (stable URL) is safer.
3. **Re-register the PayPal webhook** on the final public URL (all events), put the new ID in `PAYPAL_WEBHOOK_ID`.
4. **Demo video under 3 minutes** following `D:\Projects\Paypal\MASTER_PLAN.md` section 9 (call → pay → "got your payment" → kitchen → payout → kill a provider live → Ask your business). Record the browser call page; use the dashboard Overview for the live feed.
5. **Devpost submission:** story, built-with tags, 5+ screenshots, 3:2 thumbnail, public video link, repo link, demo URL, `docs/JUDGE_GUIDE.md` for judges (give judges the sandbox buyer email; the password is shown under developer.paypal.com → Sandbox Accounts → View details). Opt into every eligible sponsor prize (AG Grid, Render, Postman, etc.).

### P1 — gaps to close if time allows
6. **Invoicing 403:** the CallPay US app shows Invoicing ticked but the OAuth token has no invoicing scope. Try unticking → Save → ticking → Save, wait a few minutes, re-check the token scope. Only affects the Orders→Invoice fallback demo.
7. **Twilio phone number** (owner pays ~$20): set Voice webhook `<APP_URL>/voice/twilio/incoming` (POST) and status callback `<APP_URL>/voice/twilio/status`; add `TWILIO_*` keys. The TwiML flow is already built and unit-tested but has **never run against real Twilio**.
8. **Faster replies:** the local model takes ~5 s/turn. Add an `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` for ~1 s replies (over 9 s the rules engine answers instead).
9. **Chaos test** across every provider and service, and record the results for the README (MASTER_PLAN section 2, item 14).
10. **Helm on a real k3s cluster:** never installed anywhere; only linted/rendered.
11. Menu photo import (MASTER_PLAN feature 11) and Bryntum/Zapier sponsor integrations are **not built**.

## 4. New features worth adding (pick by impact vs. time)

**Step-by-step build instructions for every feature below, plus a day-by-day schedule: [`docs/FEATURE_PLAN.md`](docs/FEATURE_PLAN.md).**

**Highest demo impact (1–3 h each)**
- **Live call transcript on the dashboard**: stream `call.transcript` events into a "Live calls" panel (the events already exist).
- **QR code** for the pay link on the call page, so a judge scans it with a phone.
- **Multilingual calls** (Hindi/Tamil/Spanish): pass the language to the LLM and the browser speech APIs; the rules engine stays English-only.
- **"Recover this order" button**: one click resends the pay link for abandoned calls (the backend `remind` step already exists).
- **Order modifiers** ("no onions", "extra spicy") stored on order lines and printed on the kitchen ticket.

**PayPal depth (judging: Best Use of PayPal)**
- **PayPal Agent Toolkit / MCP** as an alternative payment-tool path for the Payments agent.
- **Venmo and Pay Later** buttons on the checkout (sandbox supports them in the US).
- **Tips at checkout**: add a tip line item; route tips straight to crew Payouts.
- **Transaction Search** reconciliation page: match PayPal settlements to orders nightly.
- **Saved payment (Vault)** for repeat callers recognized by phone number: one-tap repeat order.
- **Partial refunds per line item** from the order screen.

**Business features**
- **Bookings mode** for salons and plumbers: time slots plus deposit via PayPal (MASTER_PLAN feature 5).
- **Menu editor + photo import** with an LLM, prices still owner-confirmed.
- **Owner SMS/WhatsApp alerts** for large orders, disputes and approval requests.
- **Multi-business / multi-tenant** with per-business phone numbers.
- **Loyalty**: every 10th order free, tracked by caller phone.

**Reliability & trust**
- **Hash-chained audit log** for every money action (planned in MASTER_PLAN, not built).
- **Fraud alert actions**: Flink already emits `alerts.fraud`; show them and auto-require approval for flagged callers.
- **Load/chaos script** with a live "zero dropped orders" chart.
- **Rate limits per caller** and SMS opt-out handling.

## 5. Gotchas learned the hard way

- After rebuilding the API container, Kong may briefly 502/503 (DNS TTL is 5 s now); wait or `docker compose restart kong`.
- SQLAlchemy JSON columns: **deep-copy** before mutating (`copy.deepcopy`), or changes silently don't save (`routes_voice.py`).
- Background asyncio tasks must be awaited on shutdown (`_spawn` in `main.py`), or tests hang.
- Flink SQL client needs `rest.address` rewritten in its config (see `infra/flink/submit.sh`).
- Kong buffers responses unless `response_buffering: false` (needed for SSE `/events`).
- The dashboard uses a relative `/api`, so open it through Kong (`localhost:8090`) or the public URL, not `:3000`.
- Windows Git Bash: heredocs containing apostrophes can break; write files with an editor/tool instead.

## 6. Start everything

```bash
cd D:\Projects\Paypal\callpay
docker compose up -d
curl localhost:8090/api/health
```
Expect `postgres / kafka / temporal / clickhouse / s3`. Dashboard: http://localhost:8090 · Try a call: http://localhost:8090/call · API docs: http://localhost:8000/docs · Temporal :8088 · Flink :8082 · Grafana :3001.
