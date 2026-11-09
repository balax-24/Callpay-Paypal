# Devpost submission draft

## Project name

CallPay

## Tagline

An AI phone agent that takes local business orders, collects PayPal payment, and gets the crew paid.

## Inspiration

Small businesses can lose sales when calls go unanswered or callers drop off before paying. We wanted to make a phone call a complete path from order to payment and fulfillment, while giving the owner a live view of what is happening.

## What it does

CallPay is an AI phone agent for local businesses. A caller can speak or type an order against the business menu. The agent confirms the cart and creates a PayPal sandbox checkout link. CallPay detects the completed payment and confirms it during the call, moves the order into the kitchen workflow, and can pay crew through PayPal Payouts. The owner dashboard shows calls, orders, kitchen activity, provider health, business analytics, payouts, refunds, and dispute evidence.

## How we built it

The browser call experience and phone webhook routes feed a FastAPI service. The agent runtime combines language-model providers with deterministic rules and validates menu items against database records. PayPal Orders, capture, webhooks, refunds, disputes, and Payouts are handled by server-side adapters. Money actions pass through the application policy engine with idempotency and webhook verification. A Next.js dashboard consumes the API and live event stream. The project also includes Docker Compose, a Render blueprint, and a Helm chart.

## What is technically interesting

- The AI proposes order intent; application code loads menu prices and calculates totals.
- Payment completion can be observed during the call, allowing an immediate spoken confirmation.
- Payout and refund actions are checked against code-defined limits and approval rules.
- Provider adapters support fallbacks, while the dashboard exposes health and event activity.
- Event analytics can run through Kafka, Flink, and ClickHouse in the full local stack, with simpler fallbacks in reduced environments.

## Challenges we ran into

Making voice, asynchronous payment confirmation, order fulfillment, and crew payout behave as one flow required careful state handling. We also had to keep money calculations deterministic and separate from model output, and make the app useful when optional providers are unavailable.

## What we learned

An AI commerce experience needs explicit boundaries: AI can interpret a caller, while trusted application code validates catalog items, computes every amount, and enforces payment and payout policy. Observable events and idempotent payment operations make the end-to-end workflow easier to reason about.

## Built with

FastAPI, Python, Next.js, React, TypeScript, PayPal Orders API, PayPal Payouts API, PayPal webhooks, Docker Compose, PostgreSQL, Kafka, Apache Flink, ClickHouse, Temporal, Kong, AG Grid, Render.

## Links to fill before submission

- **Public demo:** `[add verified stable URL]`
- **Public source repository:** `https://github.com/balax-24/Paypal_Hackathon` (make public and verify first)
- **Demo video (YouTube, under 3 minutes):** `[add public video URL]`
- **Judge guide:** `docs/JUDGE_GUIDE.md`

## Accuracy checklist before publishing

- Confirm each listed integration is present in the submitted build; remove unused tags.
- Describe the tested deployment mode accurately. The full Kafka/Flink/ClickHouse stack is not represented by the current Render blueprint.
- Add the verified demo URL and confirm the public repository is accessible without login.
- Do not include sandbox passwords or secrets in this text. Provide any required sandbox testing details through the official submission’s appropriate private/access mechanism.
- Claim a phone number, real Twilio call, successful public webhook, live sandbox payment, or payout only after verifying that exact path.
