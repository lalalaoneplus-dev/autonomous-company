# Security

## Safe defaults

- Autonomy defaults to level 0.
- `REAL_MONEY_ENABLED=false` is enforced; current code supports paper mode only.
- No real payment, wallet, publication, communication, or deployment adapter executes.
- Owner authentication has no default token; the API fails closed until a unique token is configured.
- External agreement and bounty-status claims fail closed without a separately held trusted-receipt key and valid HMAC receipt.
- `BUG_BOUNTY_EXTERNAL_ACTIONS_ENABLED=false` blocks active testing, submission,
  external-status, payout, and disclosure transitions even if other evidence is supplied.
- External content never becomes policy or owner instruction.
- Audit records store concise rationales and evidence, not hidden model reasoning.

## Hard prohibitions

Policy denies wash trading, fake bids or purchases, fake reviews or testimonials, deceptive scarcity or manipulation, fraud or impersonation, phishing or credential theft, prohibited spam, unauthorized access, malware, laundering or sanctions evasion, illegal goods, policy/audit bypass, and self-permission escalation. Circumvention attempts create high-severity security events and can freeze autonomy.

## Bug bounty boundary

The Bug Bounty Agent is passive by default and external actions are disabled for
the pilot. If a later, separately authorized pilot enables them, active testing
still requires a current published scope, safe harbor, exact owner-authorized
assets, and an owner-approved bounded test plan. Submission and public
disclosure require separate owner approval; externally observed states also
require adapter evidence. The current HMAC receipt is operator-configured
attestation, not a platform signature, and must remain disabled until key ID,
rotation, replay, and signer-separation controls exist.

Immediately stop on missing authorization, scope mismatch or drift, destructive behavior, PII access/exfiltration, persistence, phishing/social engineering, denial-of-service/load testing, or credential theft.

## Incident response

1. Freeze autonomy with the owner-authenticated endpoint.
2. Preserve the database, logs, audit records, and evidence; do not delete or rewrite history.
3. Rotate exposed API keys or owner tokens outside the repository.
4. Reconcile paper/real state separately and inspect policy, security, and transaction events.
5. Fix and test the root cause, then have the owner explicitly unfreeze.

Freeze also invalidates the recurring scheduler generation. Unfreeze does not
resume old queued jobs; create a new schedule only after review.

Never commit `.env`, wallet recovery phrases, private keys, OAuth tokens, marketplace keys, or buyer-private data.
