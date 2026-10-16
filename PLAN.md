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

## Phase 1b — customers and local data (decided 2026-10-16, after the first live run)

What the first live run against 135 indirect EA enrollments showed:

- **A customer is several enrollments.** One customer is a parent enrollment
  plus two linked ones; another moved to a new enrollment mid-year, so the old one
  reads zero from then on — "data cut in the middle" was the renewal, not lost data.
- **The signed value is not readable.** Indirect EA shows no Azure Prepayment
  (all usage is overage) and the commitment lots answer 401 to a partner's sign-in.
- **Throttling is per sign-in, not per scope.** After a few page refreshes even an
  untouched enrollment answered 429. Live querying from the page cannot scale.

Decisions (operator, 2026-10-16):

| Topic | Decision |
|---|---|
| Customer | A named group of billing accounts (enrollments), across renewals and linked enrollments. Settings suggests related enrollments by name; the operator confirms |
| Loading | The plugin syncs into **local data**: one account at a time, month by month, at most twelve months per query, waiting out throttling, saving after every window so a stopped sync resumes. A settled month is never fetched again. Pages read local data only |
| Trigger | A **weekly Hermes cron job** calls `POST /plugins/azure-cost-manager/sync` (the operator creates it once; a plugin cannot). The Sync buttons call the same route |
| History | From the earliest term start among the customer's enrollments, or the signed commitment's start if earlier |
| Signed value | **Entered per customer** in Settings: commitment type, amount, currency, term start and end. The burn-down compares consumption since term start against it |
| Storage shape | Per account per month: spend by service and by subscription, actual and amortized, as name → cost maps — not the service × subscription cross product, which runs to megabytes for a large customer over three years |

**Later:** overlay the customer's sales pipeline (Opportunities) on the trend and
the burn-down, to see an opportunity's effect on consumption. *Taken up in 0.3.0.*

## Phase 1c — the operator's workbook, per customer (0.3.0, decided 2026-10-16)

The operator built a consumption workbook by hand from partner exports: a
dashboard of KPIs and charts, an automatic forecast, a driver-based forecast
with scenarios, and a pipeline of engagements with expected $ per month. The
plugin is to show the same for every customer and export it. The export's
column layout is not a contract (operator: it existed to build the sheet).

What the data showed: the export's monthly figures equal the **EA billing-period
balance** to the cent — Azure usage = `totalUsage`, Marketplace =
`azureMarketplaceServiceCharges`, Charges against Credit = `adjustments`
(e.g. a Contract Price Match Credit) — and Cost Management `ActualCost` equals
usage + marketplace, credits not subtracted. GPU SKUs show at meter level
(`MeterSubCategory`, e.g. `NDsr H100 v5 Series`); PTU shows as Azure OpenAI
reservations (`PricingModel = Reservation`).

| Topic | Decision |
|---|---|
| Measures | **Switchable.** Marketplace and credits each on/off for the dashboard's totals — Marketplace does not count toward the seller's quota, but it does burn the customer's MACC. The signed-value burn-down has its own two switches, stored with the commitment, defaulting to *include marketplace, subtract credits* |
| Balances | The sync also reads each enrollment's balance per billing period (Consumption API, a different throttle from Cost Management): usage, marketplace, credits and their named adjustments. A settled period is never read again |
| GPU / AI detail | "The more detail the better": a second Cost Management query per window, grouped by `MeterSubCategory` × `PricingModel`, classified into GPU by SKU (H100, H200, A100, A10, …), Azure OpenAI PTU (reservations) vs tokens (on-demand), and other AI — each split usage vs reservation vs savings plan |
| Dashboard | The workbook's KPIs and charts: all-time, YTD vs last year, latest month MoM/YoY, by year, YTD by year, by enrollment, quarterly by enrollment, this year vs last by month, MoM growth this vs last year, service mix by month, MACC consumed / remaining / burn / runway / exhaustion |
| Forecasts | **Automatic** — linear trend on actuals (zero months excluded) × month-of-year seasonal index, with R² and a backtest MAPE; next 12 months and next calendar year. **Scenarios** — Base / Upside / Downside monthly growth, seasonality on/off, extra uplift from a month; stored per customer. The **pipeline** adds on top |
| Export | **Values and charts only**, one `.xlsx` per customer, built by the backend with the host's `openpyxl` (framework API 9): Dashboard, Monthly, Services, Subscriptions, Enrollments, GPU & AI, Forecast, Scenarios, Pipeline |
| Pipeline | The customer's **Opportunity notes** in the vault, including its affiliates'. The plugin lists, creates and edits them — status, stage, partner, billing profile, start month and a month-by-month ramp — and the ramp feeds the forecast and the burn-down projection |
| Who writes Opportunity notes | **The Entities plugin**, which owns the `opportunity` Template. It provides the service below; this plugin calls it at request time and never writes those notes itself. Without Entities ≥ 1.1 the Pipeline tab says so and the rest works |

### The `entities.opportunities` service (provided by `sb-plugins-entities` ≥ 1.1)

Asked for with `api.get_service("entities.opportunities")` at call time.

- `customers() -> list[dict]` — every Customer hub: `{name, stem, tag, affiliates: [{name, stem, tag}]}`.
- `list_for_customer(customer_stem, include_affiliates=True) -> list[dict]` — each:
  `{id, title, stem, customer, affiliate (name | None), status, stage, product,
  route, partner, billing_profile, consumption_start, expected_monthly_usd,
  plan: [{month: "YYYY-MM", usd: int}], updated}` — `product` and `partner` are
  **lists** (as built in Entities 1.1.0), and each partner must name a Partner note.
- `create(owner_stem, title, fields, plan) -> dict` — `owner_stem` is the
  Customer's or an affiliate's hub. Writes the note the way the Template says:
  own folder, frontmatter defaults and enums, `customer/{slug}` tag, the link in
  the owner's `## Opportunities`, History and Captures children. `ValueError`
  for a rule it breaks (title taken, value not allowed).
- `update(opportunity_id, fields, plan=None) -> dict` — the allowed frontmatter
  fields, and when `plan` is given, the `## Consumption Plan` table; appends a
  line to the note's History.

### Opportunity Template v3 (in `sb-plugins-entities`)

- Frontmatter adds `billing_profile` (an enrollment / billing account number, or
  `""`) and `consumption_start` (`YYYY-MM`, or `""`).
- A `## Consumption Plan` section: a table `| Month | USD |`, one row per month.
- `expected_monthly_usd` stays, and means the plan's steady state: its last month.
- An install keeps the Template it has (the Marketplace never overwrites one), so
  the upgrade path for an existing install is that plugin's to provide.

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
