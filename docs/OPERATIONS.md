# Operations

## Local run

From the repository root:

```bash
cp .env.example .env
# Generate a unique OWNER_TOKEN and place it in .env before starting either service.
# Example generator: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
uv sync --project apps/api --extra test
cd apps/api
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd apps/web
pnpm install
pnpm dev
```

Dashboard: <http://localhost:3000>. OpenAPI: <http://localhost:8000/docs>.
Use `/health` for liveness and `/ready` for database plus configured-Redis
readiness; Redis-mode readiness returns HTTP 503 when Redis cannot be pinged.

## Verification

```bash
make test
make smoke
cd apps/web
pnpm test
pnpm build
```

The configured Docker path uses PostgreSQL and Redis. Docker is not installed on
this Mac, so Compose itself was not exercised. Isolated loopback-only Homebrew
PostgreSQL 16 and Redis 8 processes were used to verify a fresh migration to
head, Alembic drift check, a real RQ worker/scheduler dispatch, bounded schedule
decrement, cancellation, and stale-generation rejection. They were stopped
after validation; no persistent Homebrew services are enabled. SQLite/direct-
queue/mock-LLM behavior is also validated.

## Demo

From the repository root:

```bash
make seed
make cycle
```

The base setup retains autonomy level 0. `make seed` explicitly switches the
paper demo to level 3, imports labelled paper-only research fixtures, and stops at
`awaiting_owner_selection`; it cannot create an experiment, agreement,
delivery, or revenue. Normal CEO cycles remain blocked without imported real
agreement evidence.

Redis mode needs a worker in addition to Postgres/Redis. A deployment scheduler
must be running for delayed/repeated RQ jobs:

```bash
cd apps/api
QUEUE_MODE=redis uv run rq worker autonomous-company --url redis://localhost:6379/0 --with-scheduler
```

Queue a bounded recurring CEO wake-up through the authenticated endpoint:

```bash
curl -X POST 'http://localhost:8000/api/ceo/schedule?recurring=true&interval_seconds=3600' \
  -H "X-Owner-Token: $OWNER_TOKEN"
```

Only one recurring schedule can be active. Its database-backed generation is
committed before Redis enqueue and every repeated job must match it. Cancel it
explicitly when needed:

```bash
curl -X POST http://localhost:8000/api/ceo/schedule/cancel \
  -H "X-Owner-Token: $OWNER_TOKEN"
```

Direct mode rejects delay and recurrence. A recurring wake-up does not bypass
policy: without a current trusted agreement receipt and owner go, the cycle
stops. An approval records permission but does not resume work by itself; the
owner must trigger a later cycle, which revalidates the negotiation and consumes
that exact approval once before the experiment starts.

Freeze invalidates the active schedule generation and all already queued jobs
from it. Unfreeze never resumes that generation; inspect the incident, then
create a new schedule explicitly. An enqueue failure also invalidates the
reserved generation.

## Bug-bounty pilot

Keep `BUG_BOUNTY_EXTERNAL_ACTIONS_ENABLED=false`. Scope import, verification,
exact target preparation, passive triage, and report drafting remain available;
active testing, externally claimed statuses, payout, and disclosure are denied.
The flag must not be enabled until a separately authorized pilot has a real
adapter, current program scope, and an approved key lifecycle.

## Trusted receipt key

`TRUSTED_RECEIPT_HMAC_SECRET` is optional while no external adapter exists and
the API fails closed without it. The present HMAC format has no key ID, replay
registry, signer separation, or live platform attestation, so keep it unset for
the pilot. Before a real adapter, add those controls and a rotation procedure.
An operator-created page snapshot is provenance only and cannot sign an
agreement or external bug-bounty status.

## Freeze

```bash
curl -X POST http://localhost:8000/api/security/freeze \
  -H 'content-type: application/json' -H 'X-Owner-Token: YOUR_TOKEN' \
  -d '{"reason":"incident response"}'

curl -X POST http://localhost:8000/api/security/unfreeze \
  -H 'X-Owner-Token: YOUR_TOKEN'
```

## Backup and reset

Stop writers first. Back up SQLite by copying the database, or PostgreSQL with `pg_dump`; back up environment secrets separately and outside the repository. To reset only a disposable SQLite simulation, move its database aside, run `alembic upgrade head`, then reseed. Never overwrite a real or unverified database.
