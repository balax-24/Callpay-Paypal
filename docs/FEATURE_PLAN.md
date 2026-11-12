# CallPay — Feature Plan (how to build each one)

Companion to `HANDOFF.md`. Read `HANDOFF.md` sections 1 (rules) and 3 (P0 submission) first. **Submission beats features**: the hackathon closes around **Nov 12, 2026** (confirm on Devpost). Only build features after the repo is public, a stable demo URL works and the video plan is ready.

## How to use this plan

- Work top to bottom inside a wave. Each feature is independent unless "Depends on" says otherwise.
- **One feature = one branch-free small commit series on `main`**, e.g. `feat(web): live call transcript panel`. Commit as the owner only, no AI attribution (see `HANDOFF.md` §1).
- **Definition of done for every feature:** code + at least one test (API features: a pytest in `services/api/tests/`; UI: `npm run lint && npm run build` passes) + it works in the browser through `http://localhost:8090` + a line in `README.md` "What's in it" + it appears in the demo video if it's in Wave 1.
- **Money rule (never break it):** amounts always come from the database (menu prices, order totals). The LLM never sets prices, tips, refunds or discounts. New money flows go through `app/policy.py`.
- **Verify PayPal API details** against developer.paypal.com docs before coding; the request shapes below are a guide, not a copy-paste guarantee. Use the sandbox app "CallPay US".

### Where things live (quick map)

| Area | File |
|---|---|
| API routes, orders, payouts, refunds, disputes, workflow steps | `services/api/app/main.py` (`create_order`, `_mark_paid`, `_op_*`, `refund_order`, `_send_payout`) |
| Calls, phone webhooks, browser call API | `services/api/app/routes_voice.py` (`run_turn`, `poll_payment`, `end_call`, `phone_*`) |
| Agent brain | `services/api/app/agents/runtime.py` (`Planner.turn`, `OrderTaker`, `safe_say`, `crew_split`), `agents/nlu.py`, `agents/guard.py` |
| PayPal REST | `services/api/app/paypal/client.py`, `paypal/payments.py` |
| DB models + additive migrations | `services/api/app/db.py` (add columns to `MIGRATIONS`) |
| Money rules | `services/api/app/policy.py` |
| Analytics / Analyst | `services/api/app/analytics.py`, `infra/flink/analytics.sql` |
| Dashboard pages | `apps/web/src/app/*/page.tsx`, shared UI `apps/web/src/components/`, API client `apps/web/src/lib/api.ts` (`useEvents` = live SSE) |

---

## Wave 1 — biggest demo impact (do these first, ~1 day total)

### 1. Live call transcript panel on the dashboard (≈1.5 h)
**Why it wins:** judges watch a call happen live on the owner's screen; it shows the agent, the brain used (Claude/Ollama/rules) and failovers in real time.
**Backend:** nothing new. `call.transcript`, `call.started`, `call.ended`, `call.pay_link_sent`, `payment.completed` events already stream on `GET /events` (SSE).
**Frontend:**
1. New component `apps/web/src/components/LiveCalls.tsx`: `useEvents()` → keep a `Map<call_id, lines[]>` for active calls; drop a call 30 s after `call.ended`.
2. Render each active call as a card: caller, stage badge, chat bubbles (agent left, caller right), a small "brain" badge from the `llm` field (`rules` when null), a green "PAID" flash on `payment.completed` with the same `call_id`.
3. Add it to the Overview page (`apps/web/src/app/page.tsx`) above "Live events"; on mobile it stacks.
**Test:** open Overview in one tab, `/call` in another, place an order; the transcript appears live.
**Demo line:** "This is the owner's screen: every call, live, with which AI answered."

### 2. QR code for the pay link (≈45 min)
**Why:** a judge scans it and pays from their own phone; it removes the "where's the link?" moment.
**Steps:**
1. `cd apps/web && npm i qrcode.react@4.2.0` (pin a version that is at least 2 weeks old).
2. In `apps/web/src/app/call/page.tsx`, inside the "Your PayPal link" card, render `<QRCodeSVG value={call.pay_link} size={160} />` above the button; caption "Scan to pay on your phone".
3. Also show it on the Orders page detail panel when `status === "link_sent"`.
**Test:** scan with a phone, log in as the sandbox buyer, pay; the call confirms out loud.
**Note:** the pay link is a PayPal URL, so this works even when the app runs on localhost.

### 3. One-click "Resend pay link" for abandoned calls (≈1 h)
**Why:** shows missed-call recovery, a core pitch point, with one click.
**Backend:** add `POST /orders/{order_id}/remind` in `main.py` that calls the existing `_op_remind(order_id)` (it already sends the SMS via the Twilio→Telnyx chain and publishes `recovery.sent`). Return the updated order. Guard: only when `status == "link_sent"`; 409 otherwise. Rate-limit: once per 2 minutes per order (store `last_reminded_at` in `Order` via a new column + `MIGRATIONS` entry).
**Frontend:** on the Calls page and Orders page, a "Resend pay link" button for calls with status `abandoned` / orders `link_sent`. Show the channel used (`sms` or `screen`).
**Test:** pytest: create order, call endpoint twice; second call within 2 min → 429.
**Without Twilio:** the SMS chain falls back to "screen"; the button still demos the flow (the event feed shows it).

### 4. Order notes ("no onions") on the kitchen ticket (≈2 h)
**Why:** makes the agent feel real; the kitchen view becomes useful.
**Data:** add `note` to each line in `Order.items` JSON (`{"name","quantity","unit_amount","note"}`); no migration needed (JSON). Add `note: str = Field("", max_length=120)` to `OrderLine` in `main.py` and copy it into `items` in `create_order`.
**Agent:**
1. `agents/nlu.py`: extract modifiers with a small rule list: `no X`, `without X`, `extra X`, `less X`, `spicy`, `mild`; attach to the item in the same chunk.
2. `agents/runtime.py`: keep notes in the cart as `cart[item_id] = {"qty": n, "note": "..."}` (update the cart helpers `_cart_lines`, `cart_total`, `cart_words` accordingly; existing tests must still pass). Ask the LLM to also return `"note"` per item in the JSON; validate length ≤ 120 and strip anything that looks like a price or URL (reuse `safe_say` checks).
3. Read notes back when confirming: "2 carne asada tacos, no onions".
**Kitchen:** Overview → Kitchen card and Orders page show notes in bold.
**Money rule:** notes never change prices. "Extra cheese" is a note, not a paid add-on (paid add-ons = a later feature with menu-priced modifiers).
**Test:** pytest: "two carne asada tacos with no onions" → item note `no onions`, total unchanged.

### 5. Multilingual calls: Hindi, Tamil, Spanish (≈3 h)
**Why:** "Most Impactful": small businesses in India serve callers in their own language.
**Steps:**
1. Add `language` to `Call.state` (default `en`). Browser call page: a language dropdown (English, हिन्दी, தமிழ், Español) sent in `POST /calls` body.
2. Speech: browser `SpeechRecognition.lang` and `SpeechSynthesisUtterance.lang` = `en-IN`, `hi-IN`, `ta-IN`, `es-ES`. Server TTS: ElevenLabs `eleven_multilingual_v2` model when language ≠ en (in `providers/voice.py`, pass language through). Twilio `<Gather language="hi-IN">` and `<Say language=...>` with a matching Polly voice.
3. Agent: add "Reply in {language}" to the OrderTaker system prompt. **Item matching stays on the English menu names**: ask the LLM to return `items` with the exact English menu names (already the contract), so the money logic is unchanged.
4. Templates: the rules engine's replies are English; for non-English calls when the LLM is down, keep English templates (acceptable fallback) or add a small translated template table for the 6 key lines (greeting, total, confirm, link sent, paid, sorry).
5. `safe_say` must still check `$` amounts; also allow `₹` if you localize currency display later (don't change currency now; PayPal sandbox business is USD).
**Test:** browser call in Hindi with a cloud LLM key → reply in Hindi, correct total, checkout works.
**Requires:** a cloud LLM key (Claude/OpenAI/Gemini) for good quality; the local model is weak at Tamil.

---

## Wave 2 — PayPal depth (for "Best Use of PayPal + AI", ~1–1.5 days)

### 6. Tips at checkout, paid straight to the crew (≈3 h)
**Why:** PayPal Orders + Payouts in one story; crew gets the tip minutes later.
**Flow:** after the order total is confirmed, the agent asks "Would you like to add a tip? 10%, 15% or none?" The tip is a fixed percentage of the DB total, computed by code.
**Steps:**
1. `Order`: add `tip` Numeric column (+ `MIGRATIONS`). `create_order` accepts `tip_pct` in {0, 10, 15, 20}; `tip = round(total * pct)`. In `PayPalClient.create_order`, add the tip as its own line item named "Tip for the crew" so `breakdown.item_total` still equals the sum (or use `amount.breakdown.handling`; item line is simpler and visible to the buyer).
2. Agent: new stage `tipping` between `confirming` and checkout in `Planner.turn`; NLU maps "ten percent", "15", "no tip" to pct. LLM may only choose from the allowed set.
3. `_op_crew_payout`: pay `crew_share_pct` of the food total **plus 100% of the tip**, split with `crew_split`. Still passes through `evaluate_payout` (auto ≤ $50).
4. Dashboard: show tip on the order and on the payout memo.
**Test:** pytest: order $9.75 + 15% tip → PayPal order body has a $1.46 tip line; payout includes it.

### 7. Venmo and Pay Later on checkout (≈3 h)
**Why:** more PayPal products in the demo; Pay Later on bigger orders.
**Option A (simplest, keep redirect flow):** in `PayPalClient.create_order`, keep `payment_source.paypal`; PayPal's hosted checkout shows Pay Later automatically for eligible US buyers and amounts. Document it and show it in the video with a larger order.
**Option B (real buttons):** a hosted checkout page in the web app, `/pay/[orderId]`, using the PayPal JavaScript SDK with `enable-funding=venmo,paylater` and `client-id` = sandbox client ID. `createOrder` returns the existing PayPal order ID (`order.paypal_ref`); `onApprove` calls the API to capture (reuse the logic in `paypal_return`, factor it into `_capture_and_mark_paid(order_id, token)`). Send this page's URL as the pay link instead of PayPal's approval link, with a QR (feature 2). Venmo buttons appear only for US buyers on mobile; sandbox Venmo has limits, so verify in docs.
**Policy:** no change; capture still idempotent (`capture-{order_id}` request ID).
**Test:** the page renders PayPal, Pay Later and (on mobile) Venmo buttons; paying via the page triggers the same "got your payment".

### 8. PayPal Agent Toolkit / MCP path for the Payments agent (≈3 h)
**Why:** the hackathon highlights PayPal's agent tooling; show the agent using it.
**Steps:**
1. Read PayPal's Agent Toolkit docs (developer.paypal.com → "Agent Toolkit"/"MCP") and confirm the current Python package name and the remote MCP server URL.
2. Add a third payment method in `paypal/payments.py`: `AgentToolkitMethod` (name `agent_toolkit`) that creates the order through the toolkit's "create order" tool, returning a `PaymentLink`. Put it **after** `orders` in `build_payment_chain` (or behind a `PAYMENTS_ORDER` setting), so the fallback chain becomes Orders → Agent Toolkit → Invoicing. It must use the same idempotency (`reference_id` = our order id).
3. Analyst agent: optionally expose read-only toolkit tools (list transactions, show order) to "Ask your business".
4. Never give the LLM refund/payout tools directly; those stay behind `policy.py` approvals.
**Test:** kill `orders` in Provider health → next checkout is created via `agent_toolkit`; the event feed shows the failover.

### 9. Settlement reconciliation with Transaction Search (≈3 h)
**Why:** an owner wants "did PayPal actually settle everything?"; shows the Reporting API.
**Prereq:** the token must include the transaction search scope (`https://uri.paypal.com/services/reporting/search/read`). It's ticked in the app; verify the scope (see `HANDOFF.md` P1 #6 for the same issue with invoicing). Sandbox transactions can take up to ~3 hours to appear.
**Steps:**
1. `PayPalClient.search_transactions(start, end)` → `GET /v1/reporting/transactions?start_date=...&end_date=...&fields=all&page_size=100` (paginate).
2. `GET /reconciliation?days=7` in `main.py`: match PayPal transactions to orders by `capture_id` (and `custom_id`); return `matched`, `missing_in_paypal`, `unknown_in_paypal`, plus fee totals.
3. Dashboard page `/reconcile` with an AG Grid and three status counts; a "Run now" button.
4. Optional: a nightly Temporal cron workflow writing results to ClickHouse.
**Test:** pytest with respx mocking the reporting response → correct matched/missing counts.

### 10. Saved payment for one-tap repeat orders (Vault) (≈4 h)
**Why:** "Same as last time?" → paid in one tap. Strong agentic-commerce story.
**Steps:**
1. On first checkout, request vaulting: in the Orders create body set `payment_source.paypal.attributes.vault.store_in_vault = "ON_SUCCESS"` (and `usage_type: "MERCHANT"`, verify in Vault docs). After capture, read the vault/payment token ID from the capture response and store it on a new `Customer` table keyed by caller phone (`phone`, `vault_id`, `last_order_items`).
2. Repeat caller: `Planner.turn` greeting checks the customer by `caller`; if found: "Welcome back! Same as last time: 2 carne asada tacos and a horchata, $9.75?" On yes, create an order with `payment_source.paypal.vault_id` and capture immediately (no buyer redirect); require a spoken confirmation of the exact total.
3. Policy: one-tap charges only up to a limit (e.g. $50) and only for the same items; otherwise fall back to the normal link.
4. Privacy: let callers say "forget my card" → delete the vault token (PayPal vault delete API) and the row.
**Test:** pytest with mocks for vault fields; manual test with the sandbox buyer.

### 11. Per-item partial refunds (≈2 h)
**Backend:** already supports partial amounts (`POST /orders/{id}/refund` with `amount`). Add `items: [{"name", "quantity"}]` to `CreateRefund`; compute the amount from the order's stored line prices (never from user input); keep the existing policy (auto ≤ $20, never above the remaining total).
**Frontend:** Orders detail panel: a checkbox per line + quantity stepper → "Refund selected ($X)".
**Agent:** Support agent can *propose* a refund of specific items from a complaint ("the horchata was spilled") → creates a `pending_approval` refund, never auto.
**Test:** refund 1 of 2 tacos → amount $3.50, status per policy.

---

## Wave 3 — business features (pick 1–2; ~0.5–1 day each)

### 12. Bookings with deposits (salons, plumbers) (≈1 day)
- New tables: `Service` (name, duration_min, price, deposit), `Slot` / `Booking` (business_id, service_id, start, status, order_id).
- Business gets `mode = "orders" | "bookings"`. In bookings mode the agent asks for service + day/time, offers 3 free slots, confirms, then takes a **deposit** via the same PayPal Orders flow (deposit = DB value).
- Temporal: reminder SMS 24 h before; no-show → keep deposit; cancel > 24 h → refund deposit through `policy.py`.
- Dashboard: a simple day calendar (AG Grid rows by time is fine; Bryntum is a sponsor option).
- Seed a second business "Priya's Salon" to demo.

### 13. Menu editor + photo import (≈5 h)
- `GET/POST/PUT/DELETE /businesses/{id}/menu` + a Menu page with an editable AG Grid.
- Photo import: `POST /menu/import` (multipart image) → vision LLM (Claude/OpenAI/Gemini with image input) returns `[{"name","price"}]` → shown as a **draft** the owner must confirm before saving (prices are never auto-saved).
- Store the photo in object storage (`state.store.put_json` pattern; add a `put_bytes`).

### 14. Owner alerts by SMS or WhatsApp (≈2 h)
- Setting `OWNER_PHONE`. Event-bus hook (`state.bus.hooks`) that sends a short SMS through `_send_sms` on: payout/refund `pending_approval`, `dispute.updated`, order total > $100, `alerts.fraud`.
- WhatsApp: Twilio WhatsApp sandbox uses the same Messages API with `whatsapp:` prefixed numbers; add a `TwilioWhatsApp` provider to `providers/voice.py` SMS chain behind a setting.
- Throttle: max 1 alert per type per 5 minutes.

### 15. Multiple businesses on one install (≈4 h)
- Already partly modelled (`business_id` everywhere). Add: `POST /businesses`, a business switcher in the dashboard header (store choice in `localStorage`), filter all list endpoints by `business_id`.
- Phone routing: one Twilio number per business; `/voice/twilio/incoming?business_id=...` already supported (query param) — set it per number in Twilio.

### 16. Loyalty program (≈2 h)
- `Customer` table keyed by phone (shared with feature 10): `visits`, `points`.
- After `payment.completed`, increment visits. Every 10th order: the agent offers "your 10th order, the cheapest item is free"; implement as a **DB-computed discount line** (negative item) validated by `policy.py` (max discount = cheapest item price).
- Show loyalty on the Calls page.

---

## Wave 4 — trust & safety (great for the "production-grade" story; ~0.5 day each)

### 17. Tamper-evident audit log (≈3 h)
- Table `AuditLog(id, ts, actor, action, entity, entity_id, data JSON, prev_hash, hash)`; `hash = sha256(prev_hash + canonical_json(row))`.
- Write an entry for every money action: order created/paid, payout requested/approved/sent, refund requested/decided/sent, dispute evidence submitted, provider kill/revive. A helper `await audit(actor, action, entity, id, data)` in `main.py`.
- `GET /audit/verify` recomputes the chain and returns the first broken link.
- Dashboard "Audit" tab with a "Verify chain ✓" badge.
- Test: tamper a row in SQLite in the test → verify reports it.

### 18. Act on Flink fraud alerts (≈3 h)
- Flink already writes `alerts.fraud` (caller with > 5 calls in 10 minutes). Add a Kafka consumer in the API (aiokafka, background task via `_spawn`) that stores `FraudFlag(caller, reason, until)`.
- Effects: flagged callers can still order, but checkout is limited (e.g. max $30) and any refund for them goes to `pending_approval`; the dashboard shows a red badge on their calls.
- Fallback when Kafka/Flink are down: compute the same rule from the `calls` table in the API.
- Test: insert a flag → refund request becomes `pending_approval`.

### 19. Load/chaos test with a "zero dropped orders" chart (≈4 h)
- `scripts/chaos.py`: runs N concurrent simulated calls (`POST /calls` → turns → checkout), while every 20 s it kills/revives a random provider via `/providers/{layer}/{name}/kill|revive`. PayPal calls should be mocked or limited (sandbox rate limits): add a `PAYMENTS_FAKE=1` mode that returns a fake approval link and auto-marks paid after 2 s, **for load tests only**.
- Output a CSV/JSON summary: calls started, orders created, orders paid, errors, failovers by layer.
- Dashboard `/chaos` page (or a README chart image) plotting orders/min vs. failovers; headline "0 dropped orders across N failovers".
- Great 20-second clip for the video.

### 20. Per-caller rate limits (≈1.5 h)
- Redis is already in the stack (`REDIS_URL`): sliding-window counter per caller phone / per client IP for `POST /calls`, `/turn`, and `/orders`. In-memory fallback if Redis is down (same pattern as the event bus).
- Limits (config): 5 calls / 10 min per caller, 30 turns / call, 3 checkouts / hour per caller. Return 429 (browser) or a polite `<Say>` + hangup (Twilio).
- Kong already has a global 600/min limit; this is per caller.

---

## Suggested schedule if you have ~2.5 days before submitting

| When | Do |
|---|---|
| Day 1 morning | P0 from `HANDOFF.md`: repo public, Render deploy, webhook on the published URL |
| Day 1 afternoon | Wave 1: features 1, 2, 3 (live transcript, QR, resend link) |
| Day 1 evening | Feature 6 (tips → crew payouts) |
| Day 2 morning | Feature 4 (order notes) + feature 17 (audit log) |
| Day 2 afternoon | Feature 7 option A or B (Pay Later/Venmo) + feature 19 (chaos chart for the video) |
| Day 2 evening | Record the video (MASTER_PLAN §9), screenshots |
| Day 3 | Devpost write-up, final checks, **submit ≥ 6 h early**. Only then: feature 5 (multilingual) or 10 (vault) if time remains |

Skip anything not finished and tested by the end of Day 2; a polished smaller demo beats a broken bigger one.

## Demo script additions (if built)
- Scan the QR on screen with a phone, pay, and the agent confirms out loud (features 2, 1).
- Add a 15% tip, then show the tip arriving in the crew payout (feature 6).
- Run the chaos script while placing a call: "zero dropped orders" (feature 19).
- "Verify chain ✓" on the audit log (feature 17).
