# Architecture

## Stack

- Control plane: FastAPI, SQLAlchemy, and Alembic.
- Dashboard: Next.js, TypeScript, and Tailwind CSS.
- Configured production data plane: PostgreSQL and Redis through Docker Compose.
- Validated data paths: SQLite/direct/mock plus isolated PostgreSQL 16 and Redis
  8 with a real RQ worker/scheduler. Docker/Compose remains untested because
  Docker is not installed on this Mac; no database or queue service is left running.

## Control flow

1. The owner or explicit demo route starts a bounded CEO cycle.
2. The CEO loads persisted state, agents, memory, experiments, and opportunities.
3. Every proposed tool action enters the tool broker.
4. Deterministic policy returns `ALLOW`, `DENY`, or `REQUIRE_APPROVAL` and persists the decision.
5. Allowed paper transactions use the integer-cents double-entry ledger.
6. Outcomes, evidence, audit events, model usage, and postmortems are persisted.

Redis recurrence uses one persisted CEO-schedule row. Each activation gets a
new UUID generation; workers lock and claim only the current active generation,
serialize runs, decrement a bounded remaining-run count, and reject stale,
cancelled, busy, exhausted, or frozen jobs. Freeze/cancel rotates the generation
so unfreeze cannot revive queued work. Direct mode remains one-shot.

The manager-agent roster is the CEO plus Research, Builder, Marketing, Sales, Finance, Risk/Critic, Verification, and passive Bug Bounty specialists. Permissions are declarations; the broker and policy engine remain authoritative.

## Revenue portfolio

One shared pipeline serves five streams: agent services/research, licensable digital assets, public tasks/bounties, affiliate/content, and bug bounty. Real commercial work must follow:

`untrusted demand evidence -> qualification -> real two-way negotiation -> scope/price/acceptance -> owner go/no-go -> build -> artifact proof -> owner PAPER/REAL decision -> delivery/settlement`

A listing, bid, demo fixture, or model assertion is not an agreement. Paper and real metrics never aggregate.

## Trust boundaries

- External pages, marketplace listings, messages, and uploads are untrusted data.
- The owner token is an environment secret; the browser keeps a user-entered token only in `sessionStorage`.
- Real payment and wallet adapters are inert.
- Bug-bounty external actions are configuration-disabled by default; passive
  preparation does not imply authorization to test or submit.
- The optional OpenAI Agents SDK bridge requires `LLM_MODE=openai` and an API key, and remains intentionally non-executing in this paper MVP.
