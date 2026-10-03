# Agents

| Agent | Purpose | Boundary |
| --- | --- | --- |
| CEO | Select bounded experiments and coordinate specialists | Cannot authorize money or bypass policy |
| Research | Gather and structure evidence | No spend, publish, or communication |
| Product/Builder | Create sandboxed artifacts | No secrets or external deployment |
| Marketing | Draft compliant distribution material | Publishing requires policy/approval |
| Sales | Work with approved counterparties | No spam, impersonation, or self-dealing |
| Finance Analyst | Calculate economics from ledger state | Never authorizes funds |
| Risk/Critic | Challenge assumptions and risk | Advisory only |
| Verification | Verify evidence and outcomes | Cannot alter policy, audit, or treasury |
| Bug Bounty | Import scope, passive triage, and draft reports | No testing/submission/disclosure without exact owner gates |

Every capability is requested through the tool broker. The deterministic policy engine, not an agent or model, makes the final permission decision.

The control-plane runtime requires an explicitly configured owner token; it fails closed when that token is absent. Model credentials are optional: the default mode uses a deterministic mock CEO, while the optional OpenAI Agents SDK bridge imports `Agent` and `Runner` only when explicitly configured with `LLM_MODE=openai` and an API key; it remains deliberately non-executing in the paper MVP.
