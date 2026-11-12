# CallPay — Agent Handoff (Nov 9, 2026)

Read this first, then `README.md`. Older planning notes live one folder up: `D:\Projects\Paypal\RESUME.md`, `MASTER_PLAN.md`, `ARCHITECTURE.md`.

> **DEADLINE FIRST.** The [Devpost Official Rules](https://paypalaihackathon.devpost.com/rules) list the deadline as **Nov 12, 2026 at 12:00 PM Pacific Time**. With the current PST offset, that is **Nov 13 at 1:30 AM IST**. Target submission at least 6 hours early: **Nov 12 at 7:30 PM IST**. Submission (section 3, P0) beats every new feature.

---

## 1. Rules for whoever continues

- **Sole author.** The owner is the only contributor. Commit as `Balaharish Saravanan <balaharish0202@gmail.com>` (already set in this repo's git config). **Never add `Co-Authored-By` or any AI attribution** to commits, PRs, README or the Devpost text.
- **Small commits, one per stage** (`feat(...)`, `fix(...)`, `docs:` style). Normal pushes only, **never force-push** `main`.
- **Never paste secrets into chat or commits.** Keys live only in `callpay/.env` (git-ignored). The PayPal sandbox app is **"CallPay US"** (US business `sb-guxbp53788085@business.example.com`).
- Don't type passwords into websites. Paying as the sandbox buyer is done by the owner.
- Run tests before every commit: `cd services/api && .venv/Scripts/python -m pytest -q` (48 passed on Nov 12), plus `cd apps/web && npm run lint && npm run build`.

## 2. What works today (verified live on Nov 8–9)

Full loop with a real sandbox payment: browser call → agent builds the cart from the menu DB → PayPal Orders checkout link → buyer pays → capture + 2 signature-verified webhooks → **agent says "got your payment" on the call** → Temporal workflow: kitchen → ready → **automatic crew payout via PayPal Payouts** (policy engine: auto ≤ $50, owner approval above).

Also working: refunds (auto ≤ $20, approval above), dispute evidence drafted from the transcript, Kafka → Flink (job `callpay-analytics` RUNNING) → ClickHouse, "Ask your business" analyst, Next.js + AG Grid dashboard with live provider kill/revive, object storage for transcripts, Grafana dashboard, Helm chart (lints), Render blueprint, CI (api/web/compose/helm green after the last fix).

**Fallback chains** (every layer degrades instead of failing): LLM Claude→OpenAI→Gemini→Ollama(host)→Ollama(Docker)→rules engine · STT Deepgram→AssemblyAI→Whisper→browser · TTS ElevenLabs→Cartesia→OpenAI→browser · SMS Twilio→Telnyx→on screen · payments Orders→Invoicing · workflows Temporal→in-process · events Kafka→memory · analytics ClickHouse→Postgres · DB Postgres→SQLite · storage S3→disk · gateway Kong→Caddy.

## 3. Remaining work, in priority order

### P0 — needed to submit (do these first)
1. **Make the GitHub repo public** (`balax-24/Paypal_Hackathon`; MIT license already in place). Owner does this in GitHub settings.
2. **Public demo URL.** Publish with the Render Blueprint in [`docs/RENDER_DEPLOYMENT.md`](docs/RENDER_DEPLOYMENT.md) (single Docker service + free Postgres). The Cloudflare quick tunnel (`scripts/tunnel.ps1`) is temporary; its URL changes on restart.
3. **Register the PayPal webhook** in the sandbox app against the final URL: `<public-url>/api/webhooks/paypal`. Put the returned webhook ID in the Render service's `PAYPAL_WEBHOOK_ID` environment variable and redeploy.
4. **Demo video under 3 minutes** following `D:\Projects\Paypal\MASTER_PLAN.md` section 9 (call → pay → "got your payment" → kitchen → payout → kill a provider live → Ask your business). Record the browser call page; use the dashboard Overview for the live feed.
5. **Devpost submission:** story, built-with tags, 5+ screenshots, 3:2 thumbnail, public video link, repo link, demo URL, `docs/JUDGE_GUIDE.md` for judges (give judges the sandbox buyer email; the password is shown under developer.paypal.com → Sandbox Accounts → View details). Opt into every eligible sponsor prize (AG Grid, Render, Postman, etc.).

**Session update (Nov 9):** Drafted `docs/DEMO_SCRIPT.md` and `docs/DEVPOST_DRAFT.md`; revised `docs/JUDGE_GUIDE.md` to avoid promising an unconfigured phone number or guaranteed payout/fallback. Fixed `render.yaml` to set the web Dockerfile path and wire the web build to the API's full public `RENDER_EXTERNAL_URL` (verified against Render's official blueprint/environment docs). `docker compose up -d --build` succeeded; browser verification through `http://localhost:8090` covered the dashboard, menu, browser call, transcript, $9.75 menu total, code-computed 15% tip ($1.46), $11.21 sandbox checkout link + QR, screen reminder fallback + two-minute cooldown, Calls history, Audit integrity verification, and Chaos runs page. All app routes and `/api/health` + `/api/audit/verify` returned 200. The test call was closed as `abandoned` before payment; payment/payout verification was completed in the later session update below. The live-call panel now retains active checkouts for the 15-minute payment wait, and the Chaos page has no unmeasured sample data. API tests: 38 passed; web lint/build passed. GitHub repo public status, Render deployment, public webhook, screenshots, and video remain unverified.

**Session update (Nov 9, sandbox payment recovery):** The owner completed the $11.21 sandbox checkout (including the code-computed $1.46 crew tip), but the old Cloudflare quick-tunnel return URL was no longer reachable. Restarted the full Docker Compose stack, replayed the buyer-approved return through the local CallPay endpoint, and confirmed PayPal capture + database payment. Found the local `.env` lacked `INTERNAL_API_TOKEN`, so Temporal activities were receiving 403s; generated a random token in the ignored `.env` and recreated API + worker. The first Temporal workflow had already failed, so resumed the paid order with a recovery workflow through the same policy-controlled fulfillment/payout steps. Verified in the live dashboard at `http://localhost:8090`: order `#257db6` is `ready`; crew payout is `$2.44`, `sent` via PayPal Payouts and policy, split `$1.22` per crew member. API health is green. This verified payment → kitchen → payout, but the call had already ended before payment, so spoken payment confirmation during that call was not tested. The owner then started a quick tunnel at `https://thank-smoke-twenty-portsmouth.trycloudflare.com`; `/`, `/orders`, `/payouts`, `/call`, and `/api/health` returned 200. Updated local ignored `.env` `APP_URL` to that URL with `/api` suffix and recreated the API. Quick Tunnel URLs are ephemeral; the PayPal webhook route is `<current-tunnel-url>/api/webhooks/paypal` (not `/api/paypal/webhook`). A Replit-shaped single-port runtime was tested locally and later superseded by the Render deployment path. Public webhook delivery, demo video, and Devpost submission remain unverified. Demo/Devpost drafts and `scripts/chaos.py` remain local/uncommitted.
**Session update (Nov 9, Replit readiness):** A Replit-shaped API/Next.js launcher and streaming gateway were smoke-tested locally, including API routing and SSE. Those Replit-specific config/docs were removed on Nov 12 after the owner selected Render's free plan; the generic launcher/gateway are now named `callpay_start.py` and `callpay_gateway.mjs` and are used by the Render Dockerfile.

**Verification update (Nov 9):** API suite: 40 passed. Web lint and production build passed. `docker compose config -q` and `docker compose up -d --build` passed; app routes `/`, `/orders`, `/payouts`, `/call`, `/calls`, `/chaos`, `/analytics`, `/audit`, `/api/health`, and `/api/audit/verify` returned 200 through `http://localhost:8090`; the audit chain is valid. `/api/events` streamed its initial SSE chunk immediately. Current quick tunnel health returned 200; the webhook path resolves to its POST-only endpoint (GET returned 405). No public Render deploy, live webhook delivery, same-call payment confirmation, or new sandbox payment was tested in this session. The localhost and tunnel checks do not replace owner verification after hosting.

**Feature work (Nov 9):** Added the Overview live-call panel, QR checkout on call/order views, a two-minute per-order resend endpoint/button, modifier notes on order lines and kitchen displays, code-computed optional crew tips (0/10/15/20%) passed to PayPal as a line item and routed 100% to crew on top of the food-share payout, multilingual browser-call controls (English/Hindi/Tamil/Spanish, LLM instruction while preserving English menu validation), hash-chained audit entries + verification page, item/quantity refunds computed from stored order prices, an intake-only chaos runner/chart, and shared-token authentication for Temporal internal workflow steps. After Docker became available, the browser flow was exercised and found a live-call expiry issue; the panel now keeps active calls visible through the 15-minute payment wait. API tests: 38 passed; web lint/build and Compose builds passed. `.env.example` calls out `INTERNAL_API_TOKEN`; the owner needs the same random secret in API and worker configuration for Temporal activities. Demo/Devpost drafts and `scripts/chaos.py` remain local/uncommitted. Project code is committed and pushed; no real-money payment or payout was performed.

**Feature work (Nov 12):** Added `services/api/app/routes_ops.py` with four owner features, plus dashboard pages `/menu`, `/reconcile`, `/safety`. (1) Menu editor: add/rename/reprice/remove items, audited, live on the next call. (2) PayPal reconciliation via Transaction Search (`GET /reconciliation?days=`): matched / amount differs / not in report yet / missing, fees and net. (3) Fraud guard + per-caller limits: 5 calls in 10 minutes flags a number for 60 minutes (checkout capped at $30, refunds forced to owner approval); hard limits of 8 calls per window, 3 checkouts per hour, 60 turns per call; owner can flag or clear manually. The rule is computed in the API from the calls table; the Flink `alerts.fraud` topic is **not** consumed yet. (4) Owner alerts for approvals, failed payouts, disputes, fraud flags and large orders, with a 5-minute cooldown per type; texted when `OWNER_PHONE` and an SMS provider are set, otherwise shown on the dashboard. **Verified:** API tests 48 passed; web lint/build passed; rebuilt Compose and checked all four through `http://localhost:8090`; reconciliation ran against the real sandbox and matched both paid orders ($20.96 gross, $1.71 fees). **Not verified:** alert delivery by real SMS (no Twilio), and none of this on Render. The PayPal token now includes the invoicing and transaction-search scopes, so P1 #6 may be resolved; the Orders→Invoice fallback has not been retested.

**Redesign (Nov 12):** `/` is now a landing page (what CallPay does, example call, fallback chains, money rules, "Try a call"). The owner Overview moved to `/dashboard`. Navigation is a grouped sidebar (`Shell` in `apps/web/src/components/ui.tsx`) that collapses to a Menu button below 1024px. Verified at 1280px and 375px through `http://localhost:8090` (no horizontal overflow); web lint/build passed. Not checked on Render.

**Hosting change (Nov 12):** Replit publishing needs a paid plan, so the demo host is now **Render free plan**. Added a root `Dockerfile` (API + dashboard + gateway in one container, listening on `$PORT`), rewrote `render.yaml` as one free web service + free Postgres, and wrote [`docs/RENDER_DEPLOYMENT.md`](docs/RENDER_DEPLOYMENT.md). The launcher derives `APP_URL` from `RENDER_EXTERNAL_URL`. First Render attempt failed because Next.js tried to install TypeScript at runtime while loading `next.config.ts`, after build-time pruning removed dev dependencies; the gateway therefore never opened Render's public port. Converted the config to `next.config.mjs` and renamed the generic launcher/gateway for Render. **Verified locally after the fix:** built the root Docker image; ran with `PORT=10000` and a 512 MiB container cap connected to Postgres using a standard `postgresql://` URL; API reported PostgreSQL; launcher and Next.js started without installing packages; gateway bound `0.0.0.0:10000`; all dashboard pages, API health, and audit verification returned 200; `/api/internal/*` returned 403; SSE streamed immediately; a browser call turn returned the code-computed $7.00 menu total; peak observed use was 266.5 MiB. PayPal credentials were not attached in this test, so it did not verify checkout creation, payment, webhook delivery, spoken confirmation, or payout on Render. The remote service still needs redeployment and verification. The free plan sleeps after ~15 idle minutes.

**Next owner actions:** Make the GitHub repo public; deploy the updated Blueprint on Render and add sandbox PayPal values directly in Render; send the public URL for health/page verification; register the webhook at `<public-url>/api/webhooks/paypal` and add its ID to Render; verify live sandbox payment + spoken in-call confirmation; supply sandbox buyer access through Devpost's permitted testing instructions; record and upload the video; complete the Devpost form.

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
