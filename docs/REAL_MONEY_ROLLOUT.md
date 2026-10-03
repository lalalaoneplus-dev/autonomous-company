# Real-Money Rollout

Current support stops at stage 0. Setting `REAL_MONEY_ENABLED=true` is rejected by the API; mock financial adapters are inert.

| Stage | Capability | Exit gate |
| --- | --- | --- |
| 0 | Paper treasury | Tests, reconciliation, freeze drill |
| 1 | Testnet wallet | Threat model, isolated keys, simulation evidence |
| 2 | Tiny owner-approved real treasury | Allowlisted assets/destinations, per-action approval |
| 3 | Small autonomous budget | Proven reconciliation, limits, monitoring, incident drill |
| 4 | Profit reinvestment | Verified realized margin and dispute history |
| 5 | Expanded autonomy | Fresh legal/security review and explicit owner configuration |

Every stage requires an owner decision, separate real ledger/reconciliation, strict limits and allowlists, key rotation/revocation, anomaly monitoring, and a tested freeze/recovery path. Never place a master private key or recovery phrase in the agent runtime, browser storage, logs, prompts, database, or repository.

Before any live commerce: verify counterparty identity and terms, capture the agreed version, confirm scope/price/IP/acceptance/refund/dispute terms, and require the owner's final real-delivery decision. No wallet, bid, agreement, or payment has been created by this project.

