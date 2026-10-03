# Policy Engine

The policy engine returns exactly `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`. Each decision records the request, requesting agent, rule/reason, amount, payload, and timestamp. The tool broker executes only `ALLOW` results.

Checks cover autonomy, global/per-transaction/daily/experiment spending limits, configured category/counterparty/domain allowlists and denylists, category spending caps, model/API cost budgets supplied by the caller, per-action persisted rate-limit windows, real money and crypto, communication/publication, prohibited activity, freeze state, and approval thresholds. Usage costs are recorded only for an `ALLOW` decision; missing or malformed policy configuration fails closed. This MVP does not query a provider's live quota service.

The owner-authenticated `PATCH /api/settings` controls the nonnegative global,
per-transaction, daily, model/API, and approval-threshold limits plus JSON
allowlists/denylists/rate windows. The default material-financial approval
threshold is 250 cents. `experiment.create` requires autonomy level 1 and
`simulation.revenue` requires level 4; a matching one-time owner approval can
authorize either action when the configured autonomy level is lower.

## Commercial gates

- Imported live opportunities require an operator-attested demand-source receipt; this is persisted provenance, not platform authentication or proof that a buyer accepted an offer.
- Agreement requires verifiable two-way messages, explicit scope, price, currency, expiry, and acceptance criteria, plus an unexpired HMAC receipt produced by a separately trusted adapter.
- The owner must approve go/no-go before a real-demand experiment can be created.
- An exact owner approval may authorize one otherwise-above-autonomy action; it is consumed on execution and cannot be replayed.
- Approval is not execution: a later CEO cycle revalidates the current receipt,
  expiry, two-way messages, source evidence, freeze state, and policy before consuming it.
- The owner makes a separate immutable `PAPER` or `REAL` decision before delivery proof or settlement.
- Demo negotiations can run only through the explicit demo path and cannot qualify normal experiments.

## Bug bounty gates

Scope evidence, safe harbor, target authorization, test-plan review, active
testing, report submission, externally observed outcome, payment evidence, and
public disclosure are distinct states. The pilot configuration disables all
external-action states. If enabled later, trusted receipts and owner gates still
apply; missing authorization or unsafe activity is a hard denial.

Freeze blocks cycles and tool execution. Critical policy-circumvention events may freeze automatically; only the owner can unfreeze.
