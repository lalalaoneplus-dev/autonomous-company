# Treasury

The stage-0 treasury is an integer-cents double-entry paper ledger. Accounts include treasury, expense, revenue, and retained reserve. A transaction contains currency, amount, debit and credit accounts, experiment, agent, external reference, description, policy decision, status, and timestamp.

Authoritative balances are derived from ledger rows inside database transactions. LLM text never changes a balance. Paper and real balances, revenue, profit, and ROI remain separate.

## Seeded simulation

- Opening paper treasury: 1,000,000 cents (CAD 10,000).
- Demo expense: 200 cents.
- Demo revenue: 600 cents, explicitly simulated.
- Retained paper surplus: 400 cents.
- Delivery labels: buyer response `UNVERIFIED`, acceptance `SIMULATED`, settlement `PAPER`.

Mock fiat, card, crypto, revenue-collection, and Safe-style smart-account adapters expose integration boundaries but cannot execute real operations.

## Portfolio caps

| Limit | Default |
| --- | ---: |
| Stream committed risk | 35% |
| Counterparty/platform concentration | 20% |
| Single experiment risk | 10% |
| Bug-bounty time/compute | 5% |
| Unallocated reserve | 25% |

