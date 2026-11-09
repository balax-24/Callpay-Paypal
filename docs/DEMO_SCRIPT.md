# CallPay demo video script (target: 2:45)

Record with the browser call page and dashboard visible. Keep the video below three minutes. Use a test PayPal sandbox buyer; no real payment is involved. Only show the provider kill/recovery segment if it works in the recorded run.

| Time | Screen and action | Narration |
|---|---|---|
| 0:00–0:15 | Show CallPay Overview and Try a call. | “A missed call can mean a lost order for a small business. CallPay answers by voice, takes an order from the business menu, collects payment through PayPal, and helps the business fulfill it.” |
| 0:15–0:45 | Open Try a call, press Call, and say or type: “Two carne asada tacos and a horchata.” Then say: “That’s it.” | “The agent uses the menu to build the cart. Prices and totals come from the application’s menu data; the AI does not set amounts.” |
| 0:45–1:10 | Confirm the order and show the PayPal checkout link. Open checkout and pay with a sandbox buyer. | “CallPay creates a PayPal checkout link. I’ll complete this with a sandbox buyer.” |
| 1:10–1:30 | Return to the call and show the payment confirmation; keep Overview open if possible. | “When payment is confirmed, the agent acknowledges it while the call is still active.” |
| 1:30–1:55 | Show the kitchen card, then Payouts & approvals. | “The paid order moves into fulfillment. Crew payouts are calculated in code and checked by a policy engine before PayPal Payouts sends them.” |
| 1:55–2:20 | Show live events and provider health. If verified live, kill a non-payment provider, demonstrate a turn using its fallback, then revive it. | “The dashboard streams call and business events. Provider fallbacks help the call continue when an integration is unavailable.” |
| 2:20–2:40 | Show Ask your business and a preselected question, then the repo/architecture briefly. | “Owners can ask questions about business activity. CallPay combines an AI phone agent with PayPal checkout, webhooks, refunds, and crew payouts.” |
| 2:40–2:50 | Show project name and close. | “CallPay: answer the call, get paid, and keep the order moving.” |

## Recording checks

- Keep the final cut under 3:00 and upload it publicly to YouTube.
- Use no copyrighted music or third-party marks beyond what appears in the working product.
- Capture the actual app running on screen. Do not narrate a feature that did not work in this take.
- The local Docker stack must be running and the sandbox payment must be completed by the project owner.
- If the hosted URL, sandbox payment, automatic payout, or provider failover is not working, remove that specific claim/scene and use the local run only when it is actually verified.
