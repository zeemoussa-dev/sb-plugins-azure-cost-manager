# Azure Cost Manager — plugin plan

A Second Brain plugin (`id: azure-cost-manager`, `framework_api: 7`) that reads
customers' Microsoft agreements (EA, MCA/MACC) and their monthly Azure consumption
through the Azure Cost Management and Billing APIs, analyses it, and — once a
billing account is linked to a Customer — stores it in the vault so agents can
answer consumption questions.

Status: **plan, not started.** Decisions below were taken with the operator on
2026-10-16.

---

## Decisions

| Topic | Decision |
|---|---|
| Data source | Azure Cost Management + Billing REST APIs, called by the plugin backend |
| Auth | The operator's own `az login`. The backend runs `az account get-access-token --resource https://management.azure.com/` and calls the APIs with `httpx` (already a framework dependency). No secrets stored; an expired sign-in is reported on screen, never retried silently |
| Agreements | EA, MCA (incl. MACC), or mixed — read `agreementType` from each billing account and branch on it |
| Analysis (v1) | Month-over-month trend, commitment burn-down, top services & anomalies, forecast |
| Customers | The plugin keeps its **own list** of tracked billing accounts. Each may optionally be **linked** to an Entities Customer, because the Azure name often differs from the Customer note's name |
| Storage | **Phase 1: display only** (plus a cache). **Phase 2:** once linked, write vault notes **and** raw data |
| Vault writes | Written directly, as `sb-plugins-action-center` does (the Plugin API has no vault write) |
| Q&A | A plugin screen, plus an ADR-032 **Workflow** (with its Actions) the operator installs from the plugin's Settings page |
| Workflow install | Both: now, ship an `.sbf` and import it through the framework's artifact import endpoint; later, the framework grows a Plugin API layer for Hermes content (separate framework work, see below) |

---

## Azure APIs used

| Need | Call |
|---|---|
| Accounts visible to the operator | `GET /providers/Microsoft.Billing/billingAccounts` → `displayName`, `agreementType`, id |
| Monthly cost by service / subscription | `POST {billingScope}/providers/Microsoft.CostManagement/query` — `granularity: Monthly`, grouped by `ServiceName` and `SubscriptionName`, both `ActualCost` and `AmortizedCost` |
| Forecast | `POST {billingScope}/providers/Microsoft.CostManagement/forecast` |
| EA commitment | `.../billingAccounts/{id}/providers/Microsoft.Consumption/balances` |
| MACC commitment | `.../billingAccounts/{id}/providers/Microsoft.Consumption/lots?$filter=source eq 'ConsumptionCommitment'` |

Cost Management queries are throttled per scope: cache every response and never
query a month that is already closed twice.

---

## Phase 1 — display only

**Backend** (`backend/`)

- `azure_token.py` — gets a token from `az`; a clear error when `az` is missing or signed out.
- `billing_client.py` — the five calls above, raw responses only.
- `consumption_analysis.py` — pure functions over the cached rows: monthly totals
  and MoM %, top N services, anomalies (a service's month vs its trailing
  3-month mean, threshold configurable), burn-down (consumed / remaining /
  projected exhaustion date), forecast to end of year and of agreement term.
- Data files registered with `api.register_seed_data_file`:
  `tracked-accounts.json` (billing account id, display name, agreement type,
  optional linked Customer), `consumption-cache.json` (raw query rows per
  account per month, with fetched-at).
- Router under `/plugins/azure-cost-manager/`:
  `GET /billing-accounts`, `GET|PUT /tracked`, `POST /tracked/{id}/refresh`,
  `GET /tracked/{id}/consumption?from=&to=`, `GET /tracked/{id}/analysis`.

**Screens** (`ui/`)

- Nav **Azure Cost** → `/azure-cost-manager`: tracked-account picker, trend chart,
  top-services table, anomaly list, burn-down and forecast panel, Refresh button,
  last-refreshed time.
- Settings page: list billing accounts the operator can see, tick the ones to track.

**Refresh** is on demand plus "stale on open" (current month older than a day).
There is no in-process scheduler in the framework; a monthly schedule is a
Phase 3 Pipeline.

## Phase 2 — link and store

- Settings: link a tracked account to an Entities Customer, using
  `api.get_service("entities.customers")` **at call time**; when Entities is not
  installed, linking is simply unavailable.
- On refresh of a linked account, write:
  - one note per month from a shipped Template `azure-consumption-month`
    (agreement, totals actual/amortized, MoM, top services, anomalies, burn-down,
    forecast) beside the Customer, tagged with the Customer's `customer/*` tag so
    entity-scoped answers pick it up;
  - the raw rows for that month as a CSV beside it.
- Closed months are written once; the current month is overwritten on each refresh.
- Note paths are resolved from the Customer note's location found via
  `api.vault.entries()` — never a hard-coded vault path.

## Phase 3 — questions through a Workflow

- Ship Actions (`implementation: http` → this plugin's routes):
  `azure-cost.list-customers`, `azure-cost.consumption`, `azure-cost.analysis`,
  `azure-cost.refresh`.
- Ship Workflows: **Answer a consumption question** (resolve customer → read
  consumption/analysis → answer) and **Refresh a customer's consumption**.
- Packaged as an `.sbf` in `artifacts/`; the Settings page has **Install
  consumption workflow**, which previews then commits through the framework's
  `POST /artifacts/import/preview` and `/import/commit`.
- Optional Pipeline for a monthly refresh of every tracked account.

---

## Framework work this needs (in `second_brain`, not here)

1. **Plugin API: Hermes-content layer** — ADR-022 promised plugins could carry
   Skills, agents, Actions, Workflows and Pipelines; it was never built. Doing it
   bumps `FRAMEWORK_API` to 8 and every installed plugin must be republished.
   Until then Phase 3 uses the `.sbf` import route above.
2. Nothing is needed for Phases 1–2.

## Risks / open points

- `az` must be on the backend's PATH and signed in as the operator; the backend
  process inherits it on this host, but a service-hosted backend would not.
- Billing Reader on each customer billing account is the operator's own access.
  The plugin only sees what the portal shows them.
- Writing notes outside the facade breaks if the vault layout changes; this is
  the same exposure `sb-plugins-action-center` already carries.
- `consumption-cache.json` grows with each tracked account × month. Grouped
  monthly rows are small. Revisit it if it passes a few MB.
