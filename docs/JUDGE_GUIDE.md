# CallPay judge guide

Everything runs on the PayPal **sandbox**. No real money moves.

## 1. Order by phone or browser (about 60 seconds)

**Browser demo (recommended):** open the public demo URL on the Devpost page and click **Try a call**, then press **Call** and allow the microphone (or type).
**Phone:** phone calling is available only if the submission provides a configured number. Do not assume a number is active unless one is listed on the Devpost page.

Say, for example:
1. "Two carne asada tacos and a horchata."
2. "That's it." The agent confirms the cart and offers 10%, 15%, 20%, or no crew tip.
3. Choose an option, review the final total, then say "yes". The agent creates a PayPal checkout and texts you the link (in the browser it appears next to the call, with a QR code).

## 2. Pay with PayPal sandbox
Open the link and log in with a PayPal sandbox personal buyer account. The project owner must provide judges with the correct sandbox buyer access through Devpost's testing instructions; never use a real PayPal account or real money.
Stay on the call: within a few seconds the agent says **"Got your payment"**. Nobody had to press anything; the webhook or capture landed during the call.

## 3. Watch the business side
Open **See the owner dashboard** (the **Overview** page):
- the paid order appears in **Kitchen** (preparing → ready; fulfillment timing depends on the configured workflow);
- the **Live events** feed streams every step;
- the **Live calls** panel shows the transcript and which brain answered;
- revenue analytics update through the configured stack (Kafka → Flink → ClickHouse locally, or Postgres/SQLite fallback in the reduced Render deployment);
- the crew payout workflow proposes a payout and may send it through **PayPal Payouts** if the sandbox app and crew accounts are configured; otherwise inspect **Payouts & approvals** for its queued or approval state.

## 4. Break things on purpose
In **Provider health**, press **kill** on an available AI provider and continue the call to observe fallback behavior. If all configured AI providers are unavailable, the deterministic rules engine can handle supported order turns. Payment fallback behavior depends on the PayPal account's enabled products and scopes.

## 5. Ask your business
Open **Ask your business** and try "What's my busiest hour?" or "How much did we pay the crew?". The answer is computed by code from ClickHouse, not invented by the model.

## 6. Audit and reliability view
Open **Audit log** and press **Verify now** to validate the money-action hash chain. The **Chaos runs** page charts measured intake and failover results supplied by the operator; it does not simulate checkout or paid events.

## 7. Owner tools
- **Menu**: change a price, start a new call, and the agent quotes the new price.
- **Reconcile**: press **Run now** to match paid orders against PayPal's own transaction report (new sandbox payments can take about 3 hours to appear there).
- **Safety & alerts**: flag a phone number, then try to order more than $30 from it: the agent declines politely. Alerts for approvals, disputes and flags are listed here.

## What to look for in the code
| Where | What |
|---|---|
| `services/api/app/agents/runtime.py` | Planner + sub-agents; money guardrails (`safe_say`) |
| `services/api/app/agents/nlu.py` | Rules engine that runs a call with no LLM |
| `services/api/app/paypal/` | Orders, capture, invoices, refunds, disputes, payouts, webhook verification, idempotency |
| `services/api/app/policy.py` | Approval rules for payouts and refunds |
| `services/api/app/routes_ops.py` | Menu editor, fraud guard and rate limits, owner alerts, PayPal reconciliation |
| `services/api/app/temporal_flow.py` | Durable order workflow |
| `services/api/app/routes_voice.py` | Twilio/Telnyx webhooks, live payment hold loop |
| `infra/flink/analytics.sql` | Streaming revenue windows + fraud alerts |
| `infra/helm/callpay` | k3s deployment with warm pool and autoscaling |
