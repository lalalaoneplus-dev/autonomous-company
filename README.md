# Autonomous Company — simulated control plane

This directory contains the locally authenticated full-stack control plane for the
autonomous economic-agent platform. It defaults to a paper
treasury, mock LLM, direct local queue, and autonomy level 0. Real-money mode
is disabled in code and configuration.

## Local setup

```bash
cd autonomous-company
cp .env.example .env
# Generate a unique OWNER_TOKEN and place it in .env before starting either service.
# Example generator: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
uv sync --project apps/api --extra test
cd apps/api
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd autonomous-company/apps/web
pnpm install
pnpm dev
```

The dashboard is at <http://localhost:3000> and OpenAPI is at
<http://localhost:8000/docs>. `/health` is process liveness; `/ready` probes the
configured database, requires its single recorded Alembic revision to match the
local migration head, and probes Redis when Redis mode is enabled. This base path retains autonomy level 0. The
explicit demo seed (`make seed`) switches the paper simulation to level 3; its
cycle is available at `POST /api/demo/cycle` or with `make cycle`.

On macOS, `./script/build_and_run.sh --verify` builds and installs
`~/Desktop/Autonomous Company.app`. Double-clicking the icon starts the
loopback-only API and dashboard, keeps its generated owner token in an
owner-only Application Support file, and opens the authenticated dashboard in
a dedicated app window. It does not seed data, raise autonomy, or enable
real-money or external bug-bounty actions.

Public-demand snapshots are imported as untrusted evidence; the API never
contacts the source or the named buyer. An owner-attested source receipt can
record URL, platform, identity, timestamps, quoted need, budget, currency, and
content hash, but is explicitly not platform-signed proof:

```bash
curl -X POST http://localhost:8000/api/demand-evidence \
  -H 'content-type: application/json' -H "X-Owner-Token: $OWNER_TOKEN" \
  -d @demand-snapshot.json
```

Negotiation evidence must contain real two-way message records plus an
unexpired `trusted_adapter_hmac_v1` receipt before a counterparty can be marked
agreed. Configure `TRUSTED_RECEIPT_HMAC_SECRET` only in a separate trusted
adapter; an owner-attested page snapshot alone never qualifies. Missing,
invalid, or expired receipt evidence fails closed. The owner then makes the
go/no-go decision, and a separate `PAPER`/`REAL` delivery decision gates any
settlement. The demo uses a clearly labelled synthetic UI fixture only; it does
not represent a real buyer, contact, acceptance, delivery, or payment. Its
proof is always `buyer_response=UNVERIFIED`, `acceptance=SIMULATED`,
`settlement=PAPER`.

The CEO portfolio is keyed by `stream_type`: `agent_services`,
`digital_assets`, `public_tasks`, `affiliate_content`, and `bug_bounty`.
`GET /api/portfolio` reports per-stream opportunities, paper revenue/cost,
committed risk, and explicit concentration/reserve caps. The seeded rows are
local fixtures, not live demand.

Bug-bounty scope is imported as evidence at `POST /api/bug-bounty/programs`.
The passive-by-default Bug Bounty Agent records scope, rules, rate limits,
test-account/header requirements, payout tiers, and disclosure policy. Exact
owner authorization is required before the `ACTIVE_TESTING` state. In this
pilot, `BUG_BOUNTY_EXTERNAL_ACTIONS_ENABLED=false` additionally rejects active
testing, submission and external outcomes, payout, and disclosure. Enabling the
flag later preserves the owner and trusted-receipt gates but still adds no
scanner, report client, credential access, or bounty revenue booking; paper
payment outcomes remain labelled and outside the treasury.

## PostgreSQL and Redis

Docker is optional for the local SQLite/manual path. When Docker is available:

```bash
docker compose up -d postgres redis
DATABASE_URL=postgresql+psycopg://company:company@localhost:5432/company \
  QUEUE_MODE=redis uv run --project apps/api alembic upgrade head
```

Redis jobs are enqueued with bounded retries. The direct queue is the explicit
local/manual path and executes one bounded cycle immediately. Run an RQ worker
with its scheduler for Redis mode:

```bash
cd apps/api
QUEUE_MODE=redis uv run rq worker autonomous-company --url redis://localhost:6379/0 --with-scheduler
```

Then queue a bounded recurring wake-up (at most `MAX_CYCLES`) through the
authenticated API:

```bash
curl -X POST 'http://localhost:8000/api/ceo/schedule?recurring=true&interval_seconds=3600' \
  -H "X-Owner-Token: $OWNER_TOKEN"
```

Only one durable recurring generation can be active. Cancel it with
`POST /api/ceo/schedule/cancel`. A freeze invalidates its generation, so queued
pre-freeze jobs remain harmless after unfreeze; the owner must create a new
schedule. Approving a queued action also does not start it automatically: run
one fresh CEO cycle so policy and agreement evidence are revalidated and the
approval is consumed exactly once.

## Safety boundary

All tool calls pass through the deterministic policy engine and tool broker.
Paper ledger entries use integer cents and atomic double-entry writes. Mock
adapters implement the interfaces for fiat/card/crypto/revenue, Safe-style
wallet controls, research/publishing/communication/sandbox/analytics/
marketplace/NFT actions, but never contact those services. The optional OpenAI
bridge validates its package and key but intentionally does not execute model
proposals in this paper phase; the default mock mode needs no model credential.

## Verification

```bash
make test
make smoke
cd apps/web
pnpm test
pnpm build
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/SECURITY.md`](docs/SECURITY.md), and
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the operating boundaries.
