# CallPay judge guide

Everything runs on the PayPal **sandbox**. No real money moves.

## 1. Order by phone or browser (about 60 seconds)

**Phone:** call the number on the Devpost page.
**Browser:** open the dashboard and click **Try a call**, then press **Call** and allow the microphone (or just type).

Say, for example:
1. "Two carne asada tacos and a horchata."
2. "That's it."
3. "Yes." The agent creates a PayPal checkout and texts you the link (in the browser it appears next to the call).

## 2. Pay with PayPal sandbox
Open the link and log in with the sandbox buyer account listed on the Devpost page. Approve the payment.
Stay on the call: within a few seconds the agent says **"Got your payment"**. Nobody had to press anything; the webhook or capture landed during the call.

## 3. Watch the business side
On the dashboard **Overview**:
- the order moves to the **Kitchen** (preparing → ready);
- the **Live events** feed streams every step;
- revenue updates (Kafka → Flink → ClickHouse);
- a crew payout is proposed and, under $50, sent automatically through **PayPal Payouts** (see **Payouts & approvals**).

## 4. Break things on purpose
In **Provider health**, press **kill** on the live AI provider, then keep talking on the call. The next provider answers; if all are killed, a rules engine still finishes the order. Do the same for PayPal Orders: the next checkout is a PayPal Invoice.

## 5. Ask your business
Open **Ask your business** and try "What's my busiest hour?" or "How much did we pay the crew?". The answer is computed by code from ClickHouse, not invented by the model.

## What to look for in the code
| Where | What |
|---|---|
| `services/api/app/agents/runtime.py` | Planner + sub-agents; money guardrails (`safe_say`) |
| `services/api/app/agents/nlu.py` | Rules engine that runs a call with no LLM |
| `services/api/app/paypal/` | Orders, capture, invoices, refunds, disputes, payouts, webhook verification, idempotency |
| `services/api/app/policy.py` | Approval rules for payouts and refunds |
| `services/api/app/temporal_flow.py` | Durable order workflow |
| `services/api/app/routes_voice.py` | Twilio/Telnyx webhooks, live payment hold loop |
| `infra/flink/analytics.sql` | Streaming revenue windows + fraud alerts |
| `infra/helm/callpay` | k3s deployment with warm pool and autoscaling |
