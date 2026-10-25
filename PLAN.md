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

## Phase 1e — groups: a parent's MACC carved out to affiliates (decided 2026-10-17)

A holding group signs one MACC (say $50M); its affiliates each sign their own
MACC (say $7M) that is **carved out of** the parent's. In Azure each affiliate is
its own enrollment(s), linked under the parent's enrollment.

| Topic | Decision |
|---|---|
| Structure | A **parent customer** and **affiliate customers**, each affiliate a full customer (enrollments, dashboard, export, pipeline) with `parent` set. One level only |
| Signed values | The parent's commitment is the group's whole MACC. An affiliate's commitment is its own MACC, a **fixed amount**, counted against the parent's |
| Burn | Every dollar an affiliate consumes counts against its own MACC **and** the parent's. The parent's view rolls up its own enrollments and all its affiliates' |
| Allocation | The parent shows each affiliate's MACC, consumption, pace and projection; the **unallocated** part (parent MACC − affiliates' MACCs) against the parent's own enrollments; and over-allocation when affiliates' MACCs exceed the parent's |
| Sync | Syncing the parent syncs its affiliates |
| Vault | Affiliates link to their affiliate notes; the missing ones are created through `entities.opportunities.create_affiliate` (Entities ≥ 1.2) |

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

## FinOps — pay less for the same, and keep it that way (proposed 2026-10-17)

Operator, 2026-10-17: add FinOps "based on the consumption", as a report or a
section; for **both** audiences — "Different Views One for me one for the
Customer". The plugin already does FinOps' *Inform* phase (consumption, burn,
anomalies, Marketplace); this adds *Optimize* (rates and usage) and *Operate*
(budgets and alerts), and turns findings into pipeline.

### Two views of the same findings

| | **Account view** (the operator) | **Customer view** (handed to the customer) |
|---|---|---|
| Where | FinOps report per customer; **Optimization opportunities** across customers | the same report with **Customer view** on; a customer FinOps workbook |
| Shows | everything below, plus MACC pace gap, pipeline, "Create opportunity", every customer ranked | the customer's own spend, coverage, savings, budget, growth, and its own MACC burn |
| Never shows | — | other customers, and the forecast scenarios (Base/Upside/Downside assumptions) |

The Customer view is a **filter on one set of findings**, not a second
analysis: one engine, so the two never disagree. Whatever the Customer view
leaves out is left out on the server, not hidden in the browser, so an export
cannot leak it.

### What the synced data supports (checked 2026-10-17 on this install)

- The meter detail is every meter, not only GPU: `MeterSubCategory × PricingModel`
  per month. September across synced enrollments: on-demand $12.6M, reservation
  $2.2M, savings plan $0.18M, spot $8k. Top series: Premium SSD, Dsv5, Ddsv5,
  Esv5, NDsr H100 v5, Azure OpenAI, Fabric, Databricks.
- It is **actual** cost. Under actual cost a reservation shows as its purchase and
  the usage it covers costs $0, so **coverage needs the amortized meter detail**:
  one more Cost Management query per enrollment-year. Settled months are never
  fetched again, so it is a one-off backfill, then a month at a time.
- Only fully synced customers (31 enrollments today) have meters. Billing
  profiles synced lightly have totals and Marketplace only; FinOps covers
  customers.

### Phase F1 — from data this plugin can already reach (built 0.12.0, 2026-10-17)

1. **Commitment coverage**: per customer and month, the share of compute, GPU and
   Azure OpenAI covered by reservations or savings plans, against on-demand; by
   VM series. Needs the amortized meter query (sync change, above).
2. **Steady on-demand candidates**: a series running on-demand at a steady level
   (low variation) for six or more months — the classic reservation or savings
   plan case — ranked by monthly on-demand spend.
3. **Reservation purchases**: months where actual and amortized part sharply,
   which is a purchase, and how it amortizes after.
4. **Growth hotspots**: the fastest-growing services and subscriptions, plus the
   existing anomalies, framed as FinOps findings.
5. **Budgets**: a monthly budget per customer (Settings), with the forecast
   against it; over budget, or forecast to be, is flagged.
6. **Optimization opportunities** across customers: every customer ranked by
   on-demand spend on steady series and by coverage gap (Account view only).
7. The customer workbook gets a **FinOps** sheet; the Customer view has its own
   workbook, carrying only what that view shows.

### Phase F2 — savings in dollars, and findings into pipeline (built 0.13.0, 2026-10-17)

- Price each steady on-demand series as a 1- and 3-year reservation and a savings
  plan from Azure's public **Retail Prices API** (no sign-in). The meter detail
  names a series, not a SKU or a region, so a first cut prices the series'
  common SKU in the customer's main region and says so; exact figures need a
  meter-level query (`MeterId`, `ResourceLocation`), which costs throttling
  budget — decide after F1.
- **Create opportunity** on a finding (Account view): an Opportunity note through
  `entities.opportunities`, e.g. "ADNOC — 3-year savings plan for Dsv5", so FinOps
  advice lands in the pipeline. The savings free up MACC for new workloads.
- A weekly FinOps digest through Hermes (budget breaches, new candidates).

### Phase F3 — after probing what the partner sign-in can reach

- **Reservation utilization** (Consumption API reservation summaries at the
  enrollment): may answer 401 to a partner sign-in, as the commitment lots did.
- **Cost by tag** and tag coverage: possible at the enrollment, but more queries.
- Not reachable: Azure Advisor's cost recommendations need access inside the
  customer's tenant.

### Reports by tag (operator, 2026-10-17: "find Tags and Build some Reports Against the Tags")

Probed on this install, 2026-10-17:

- The Consumption API lists an enrollment's tag keys (`.../billingAccounts/{id}/providers/
  Microsoft.Consumption/tags`, 2023-05-01) to a partner sign-in, on the Consumption budget.
  ADNOC's main enrollment has 480 keys; the others 17 and 189.
- Cost Management groups an enrollment's cost by one tag key (`{"type": "TagKey", "name":
  "environment"}`): ADNOC September by `environment` added up to the month's $4,223,151 --
  prd $1.25M, untagged $748k, dev $460k, dr $451k, "non production" $381k, uat $380k, prod $208k.
- Tags are inconsistent: one idea under many keys (`projectname`, `project name`, `project_name`,
  `pojectname`, `x_projectname`; `environment`, `environemnt`, `envirornment`, `env`) and many
  values (`prd`, `prod`, `production`).

Design:

- **Dimensions**: Environment, Project, Application, Business unit, Owner, Cost centre. Each is
  found in an enrollment's tag keys by spelling -- case, spaces, `_`, an `x_` prefix and small
  typos ignored -- so `environemnt` counts as Environment.
- **One query per spelling** (Cost Management allows grouping by one tag key), only for spellings
  an enrollment actually has, at most four per dimension, for the last six closed months and the
  current one; a settled month is never fetched again. It runs as its own sync stage after
  customers and pricing, on the same throttling budget.
- **Untagged** is the month's total less what any spelling tagged. Exact for one spelling; for
  several it assumes a resource does not carry two spellings of the same dimension.
- **Values** are folded: case and spaces, and for Environment the usual synonyms (prd/prod/
  production → Production, dev → Development, uat/test/qa → Test, dr → DR).
- Reports: a **Tags** report per customer (a dimension's values by month, tag coverage, and the
  spellings found -- tag hygiene), **Tag coverage** across customers, and a **Tags** sheet in the
  workbooks. Nothing about tags is internal, so the Customer view shows it all.

### Decided (operator, 2026-10-17)

- The Customer view leaves out **only the forecast scenarios** (and, always, other
  customers). It keeps the pipeline and Opportunities, the MACC pace and gap, and
  the Marketplace MACC exceptions -- the operator chose not to hide those.
- It is handed over as a **workbook**, plus the in-app Customer view for screen-
  sharing. No PDF.
- The monthly **budget is the MACC spread evenly over its term months**, overridable
  per customer in Settings; a customer with no MACC and no override has none.

---

## Billing report — months from a billing date (requested 2026-10-21, then skipped)

**Skipped by the operator the same day ("skip that option").** Kept here only as a record of what it would take; don't build it unless asked again.

The operator wants a separate **Billing report** whose months run from a billing date, for
example the 5th to the 4th, across **all data, not only the current month** (operator,
2026-10-21). It was tried as a setting on the default report (0.30.0) and taken out the
same day (0.31.1). That setting only decided when a month counted as closed, which isn't
what was meant.

- **The constraint:** Azure reports cost by calendar month, and EA invoices, credits and
  Marketplace charges are billed per calendar billing period. A 5th-to-4th month can only
  be rebuilt from daily cost, and today daily cost is fetched only for last month and this one.
- **What it needs:** daily usage for the whole history, fetched once per settled month and
  never again, in the background like the monthly sync (a large enrollment pages 40+ times
  per month under throttling, so a first fill takes hours). Credits and Marketplace can't be
  split by day, so the report must say how it places them, or leave them out.
- **Already there:** `measure.billing_day` and `consumption_analysis.report_date` (the
  closed-month rule), which the report keeps at the 1st.

## Pipeline review: the weekly meeting as a report (planned 2026-10-25, not built)

**What it replaces.** The manager meets each account manager and the team every week to
go through the Azure opportunities they forecast, then waits for month-end to see the
numbers. Instead, the report answers four questions on its own:

1. **What changed this week?** New, won and lost opportunities, stage moves, date slips and amount changes.
2. **When will the pipeline consume, and how much?** By month, raw and weighted by stage.
3. **Did what we said would land, land?** Each opportunity's plan against what the customer actually added.
4. **Is the team the difference?** Above-baseline growth split into organic, opportunity-influenced and unexplained.

It is shown at three levels: **customer**, **account manager** (the customers they own) and
**all customers**, each drilling into the next. There are no visibility rules: everyone sees
every level (operator, 2026-10-25), and an account manager is a grouping, never a permission.

### Decisions (operator, 2026-10-25)

| Topic | Decision |
|---|---|
| Visibility | Everyone sees everything, for now. |
| Customer → account manager | An optional `account_manager: "[[<email>\|<Name>]]"` on the Customer note, linking the Person note (named by email, as the vault's meeting attendees are). An affiliate without one takes its parent's (the same rule as `industry`). Customers with none go under "No account manager". Filled for 72 customers from the team's H2 forecast workbook on 2026-10-25, together with `segment` (Strategic, Major, or Scale Accounts & ISVs), and with `pss: ["[[<email>\|<Name>]]", …]` where the workbook names a PSS. The review can group and filter by segment and by PSS as well as by account manager. |
| Stage weights | Identified 10%, Qualified 25%, Proposed 50%, Committed 80%, Won 100%. Editable in Settings. |
| Week | Closes Sunday night. Monday's report shows the week just ended. |
| Attribution | **Strict.** An opportunity's influence counts only in the services or solution it names, above that scope's own natural trend. Growth above trend with no opportunity behind it is **unexplained**, and is shown, never credited to the team. |
| Snapshots | One per week, kept in plugin data. It holds the pipeline and each scope's natural trend as they were then. |

### Why snapshots are the foundation

A natural trend recomputed today has already absorbed the growth the team drove, so the
team's impact would vanish. The trend has to be **frozen** at the time it was the honest
expectation. Each weekly snapshot freezes it, and the same snapshots give "what changed
since last week" by comparing one week with the one before. That beats parsing an
opportunity's History note: its lines are free text, and opportunities are also edited by
hand and by agents.

For opportunities that predate the first snapshot, the natural trend is fitted on the months
before each one's `created` date. This is recomputed once, kept, and labelled **estimated**
wherever it is shown.

### The data

**Already there:**
- Opportunity notes (Entities, read through `entities.opportunities`): `created`, `updated`,
  `status`, `stage`, `consumption_start`, `expected_monthly_usd`, the month-by-month
  consumption plan, `technologies` and `product`.
- The quota baseline (`quota.py`).
- The automatic forecast (`forecasting.py`: trend × seasonality, with R² and MAPE).
- Merged monthly actuals by service and by subscription.

**New:**
- **`account_manager`** on the Customer note. Documentation only in the Entities template
  (an optional key, so no version bump: Entities `MEMORY.md`, 2026-10-17). It is read through
  the vault index the way `industry.IndustryContext` reads `industry`; that reader is
  generalised to one hub-frontmatter key reader used by both.
- **`Pipeline-Snapshots.json`** (a data file, so it moves with an export). One entry per week
  (`week_end`, `taken_at`, `taken_late`), each holding:
  - every opportunity: id, stem, customer, account manager, title, status, stage, start,
    monthly figure, plan, `created` and scope;
  - for each opportunity scope, its natural trend for the next 12 months, with `fitted_through`.

  Two years are kept.
- **`Pipeline-Review.json`**: stage weights, the plan tolerance (±20% by default) and the
  horizon (12 months).

**An opportunity's scope**, for strict attribution, is taken in this order:
1. its `technologies` matched to Azure service names;
2. else the solution it was drafted from (a Compass or rule pitch), whose pattern names its services;
3. else **unscoped**.

An unscoped opportunity is still shown in sections 1–3. In section 4 it influences nothing,
and the report says "add its technologies to count its impact". This pushes data quality
without claiming growth the opportunity may not have driven.

### How snapshots are taken

- **On open:** the first time the report is opened after a week closes, it takes the missing
  snapshot. If the week closed more than a day earlier, the snapshot is marked `taken_late`.
- **`POST /pipeline/snapshot`:** for a Hermes cron job on Sunday night, as the weekly sync
  already runs. This is the reliable path, because "on open" misses weeks nobody opened.
- **"Take snapshot now"** in Settings.

### The report: what each section computes (pure functions in `pipeline_review.py`)

1. **`movement(previous, current)`:** new, won, lost, stage moved (with direction), start
   date slipped (by how many months) and amount changed. Each change carries its monthly
   impact. Until two snapshots exist, "new" is read from `created` within the week, and the
   section says so.
2. **`landing(snapshot, weights, horizon)`:** the pipeline's planned consumption by month,
   from each opportunity's plan (or its start and monthly figure), raw and weighted, stacked
   by stage. Coverage is weighted pipeline against the gap to quota (`quota.py`).
3. **`planned_vs_actual(opportunities, actuals)`:** for each opportunity whose start has
   passed, its plan per closed month against what its scope added above that scope's natural
   trend. The verdict is:
   - **landed:** within tolerance;
   - **late:** nothing yet;
   - **short** or **over**.

   Rolled up per account manager, this gives **plan accuracy** and **slip rate** (the average
   number of months starts moved).
4. **`impact(customer, period)`:** per month, the baseline, the natural trend (frozen) and
   the actual. Above-baseline growth splits into:
   - **organic:** natural trend minus baseline;
   - **influenced:** actual minus natural trend, inside the scopes of opportunities planned for
     that month. It is capped at what was planned plus tolerance, so a lucky month is not
     credited in full.
   - **unexplained:** the rest above trend.

   Each figure carries the R² of the trend it rests on. A trend that fits poorly (R² < 0.5)
   shows its figures as low confidence.

**The rollup:** customer → account manager → all customers, summed, with each level's rows
drilling into the one below.

### Compass

A **"three things to discuss this week"** summary at the top, per level and week, from the
Pipeline coach persona. It draws on:
- the biggest slips;
- opportunities that landed short;
- customers growing above trend with no opportunity;
- weighted pipeline against the gap to quota.

The checks: every item must name an opportunity or customer in the facts, and the figures
shown are the report's own. It is kept until the facts change, like the other Compass features.

### Screens

- **Pipeline review** (a new page on the Azure Customer 360 home, under "all customers"):
  - a level switch (All / an account manager / a customer) and a week picker (the snapshots);
  - the Compass summary card, foldable;
  - the four sections. A customer row drills into that customer; an opportunity row opens
    its note.
- **A customer's Pipeline tab** gains its section 4: the three lines and the split.
- **Settings → Pipeline review:** stage weights, tolerance, snapshot status and "Take snapshot now".
- **Export:** an Excel workbook with one sheet per section, for the level and week shown.

### Routes

- `GET /pipeline/review?level=all|am:<stem>|customer:<id>&week=<week_end>`
- `GET|POST /pipeline/review/summary?level=&week=` (Compass)
- `GET /pipeline/review.xlsx?level=&week=`
- `POST /pipeline/snapshot`
- `GET|PUT /pipeline/settings`

### Releases, in order

1. **Foundations:**
   - the `account_manager` key (Entities docs, and reading it here);
   - pipeline settings;
   - snapshots (on open, the endpoint, and the one-time backfill of estimated trends);
   - "No account manager" bucket counts.
2. **Sections 1–3** and the Pipeline review page at all three levels.
3. **Section 4 (team impact)**, also on a customer's Pipeline tab.
4. **The Compass summary**, the Excel export and the Settings card.

Each release is tested and installed on its own, and checked on real data before the next.

### Before it is useful (the operator's data, not code)

- Set `account_manager` on the Customer notes; the report lists the customers missing one.
- Give opportunities a `consumption_start`, an `expected_monthly_usd` (or a plan) and their
  `technologies`. The report lists the opportunities missing them, because each gap weakens a section.
- Add a Hermes cron job calling `POST /pipeline/snapshot` on Sunday night.

### Tests to pin

- The movement between two snapshots: new, won, lost, a stage moved, a start slipped, an amount changed.
- The landing calendar's weights.
- The planned-vs-actual verdicts at the tolerance edges.
- Impact sums to above-baseline. Influenced growth is capped by the plan and never
  credited outside the opportunity's scope. An unscoped opportunity influences nothing.
- A late snapshot is marked. A backfilled trend is labelled estimated.
- An affiliate takes its parent's account manager.
- Compass's summary keeps only items in the facts.

### Risks

- **Attribution is correlation, not proof.** The words on screen say "influenced by an
  opportunity", never "caused". A poorly fitting trend is flagged.
- **Service names.** `technologies` written freely won't always match Azure service names.
  An unmatched one is shown so it can be fixed.
- **Missed snapshots** if neither the cron job nor anyone opens the report. Gaps are shown,
  never interpolated.
- **Load.** One trend per opportunity scope, computed once per week and kept in the
  snapshot, never on every page view.

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
