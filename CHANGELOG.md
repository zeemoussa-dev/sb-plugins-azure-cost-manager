# CHANGELOG

All notable changes to the Azure Cost Manager plugin.

## [0.3.2] - 2026-10-16

- fix: saving a customer whose name or accounts arrive in the wrong shape answers 400 with what is wrong, instead of failing with a 500 (seen live: a name sent as a list).

## [0.3.1] - 2026-10-16

- fix: an opportunity's `partner` and `product` are lists, as Entities 1.1.0 returns them. The export wrote the list into one cell -- which `openpyxl` refuses, so any customer with opportunities could not be exported -- and the Pipeline table ran partner names together. Both now join them; the editor takes partners comma-separated, each the name of a Partner note.

## [0.3.0] - 2026-10-16

The operator's consumption workbook, for every customer, on screen and as an export (operator, 2026-10-16: "I want the Dashboard to Display Something Similar and Be Able to Export the Same for Every Customer").

- feat: **measured as invoiced.** The sync also reads each EA enrollment's billing-period balance -- usage, Marketplace and credits, which match the partner consumption export to the cent -- and the dashboard's total is switchable: **Include Marketplace** (it burns the MACC but not the seller's quota) and **Subtract credits** (e.g. a Contract Price Match Credit). The signed value has its own two switches, defaulting to Marketplace counted and credits subtracted. Enrollments without a balance are measured by Cost Management.
- feat: **GPU and AI in detail.** Meter detail (`MeterSubCategory` × `PricingModel`) classifies GPU by SKU (H100, H200, A100, A10, …) and Azure OpenAI PTU (reservations) against tokens, each split by how it was bought; the dashboard's mix by month adds up to the measured total.
- feat: **the workbook's dashboard** -- an Overview of its KPIs (all-time, YTD against last year, latest month MoM/YoY, next 12 months and next year, burn rate, runway, exhaustion, credits, Marketplace) and charts (monthly, mix, by year, YTD by year, MoM %, YoY %, this year against last, MoM growth by year, by enrollment by quarter), plus a Breakdown tab (GPU & AI, services, subscriptions, enrollments, anomalies).
- feat: **forecasts** -- the automatic trend × month-of-year seasonality model with its R² and backtest MAPE, and Base / Upside / Downside scenarios with an optional uplift, saved per customer.
- feat: **the pipeline is the customer's Opportunity notes**, its affiliates' included, through the Entities plugin's `entities.opportunities` service: link the customer to its Customer note, then list, create and plan opportunities (status, stage, partner, billing profile, start month and a month-by-month ramp). Open and Won ramps are shown on top of both forecasts and on the burn-down ("run rate + pipeline"). Without Entities ≥ 1.1 the Pipeline tab says so and the rest works.
- feat: **Export to Excel**, one workbook per customer, values and native charts: Dashboard, Monthly, Mix, Years, Services, Subscriptions, Enrollments, GPU & AI, Forecast, Scenarios, Pipeline, Commitment, Credits -- built with the host's `openpyxl`.

## [0.2.0] - 2026-10-16

What the first live run showed, and the change it forced (operator, 2026-10-16: a customer can have several tenants, data "cuts in the middle", and one customer read zero consumption for six months, which was wrong).

- feat: **a customer is a group of enrollments.** The customer reading zero had moved to a new enrollment mid-year, so its old one read zero from then on -- the "cut in the middle" was the renewal. Another is a parent enrollment plus two linked ones. Settings now builds customers from billing accounts, listing related enrollments (same name, or linked under the same parent) once one is picked; the operator decides. Every view merges a customer's enrollments, and the spend mix gains an **Enrollments** split that shows a renewal handing over.
- feat: **the signed value, entered per customer** -- type (MACC / EA commitment / Azure Prepayment / Other), amount, currency, term. Azure cannot say it here: indirect EA shows no prepayment, and the commitment lots answer 401 to a partner's sign-in. The burn-down is rebuilt on it: real cumulative consumption since term start, an even-pace line to the signed value, the run-rate projection to term end, ahead/behind pace, and any projected shortfall.
- feat: **local data, loaded by a background sync.** Cost Management throttles per sign-in, not per scope -- after a few page refreshes even an untouched enrollment answered 429 -- so pages no longer query Azure at all. `POST /sync` starts a background sync (every customer, or one) from each enrollment's term start, a year per query, waiting out throttling, saving after every window so a stopped sync resumes; a settled month is never fetched again. A weekly Hermes cron job calls it; the Sync buttons follow its progress.
- refactor: cached months are stored as service and subscription maps instead of the service × subscription cross product, which would run to megabytes for three years of a large customer. Months cached by 0.1.x are dropped and fetched again; 0.1.x's tracked accounts are carried over as one-enrollment customers.
- removed: the per-account refresh routes, and the prepayment-balance and commitment-lots calls -- the signed value now comes from the operator.
- chore: `framework_api` 9 -- the host provides `openpyxl` to plugin backends (framework `ADR-040`), which the per-customer Excel export will use.

## [0.1.5] - 2026-10-16

- fix: **a refresh on a large EA enrollment failed on Cost Management's throttling.** A twelve-month query costs about twelve of the scope's query units, so the second of a refresh's two queries was routinely told to wait 15-45 seconds, and anything over 10 failed the whole refresh. Waits of up to a minute are now absorbed, up to four attempts; a longer one still goes back to the operator with the wait Azure asked for.

## [0.1.4] - 2026-10-16

- fix: **the Azure Cost page went blank on any account with data cached.** The chart wrapper was imported from `echarts-for-react/lib/core`, which is CommonJS: the dev server hands its default import over as the module object and React refuses to render it. It now comes from `echarts-for-react/esm/core`. The publish gate type-checks and builds, but never renders, so it could not catch this.
- fix: an account with nothing billed in the last twelve months says so, instead of drawing twelve empty bars and calling last month "new".

## [0.1.3] - 2026-10-16

- fix: **indirect EA enrollments were invisible.** Billing accounts are listed on API `2020-05-01`: for a partner's sign-in, `2024-04-01` (and every version from `2021-10-01`) returned none of the enrollments `2020-05-01` returns (checked live: 0 against 135). That version also carries each enrollment's term, which the Settings list now shows and the burn-down uses.
- fix: an EA enrollment without an Azure Prepayment shows no commitment, instead of a commitment "fully consumed" -- its usage is all billed as overage.

## [0.1.2] - 2026-10-16

- feat: the charts are drawn by the host's `echarts` instead of hand-rolled SVG -- monthly spend with forecast, spend mix by service or subscription, and the commitment burn-down. Only `echarts/core`, the bar and line charts, grid, legend, tooltip, mark line and the canvas renderer are imported. Colours still come from the page's own CSS variables, read at render time because a canvas cannot resolve `var(--x)`. The ranked service and subscription rows stay HTML: their share and change columns are what is read.

## [0.1.1] - 2026-10-16

- chore: `framework_api` 8. The host now provides `echarts` and `echarts-for-react`, subpaths included, so a screen can import `echarts/core` plus only the chart types it draws (framework `ADR-039`). The gate is exact-match and refuses a plugin at load, so this republish is what keeps the page loading. This plugin is the reason the capability exists: its cost page draws hand-rolled SVG charts, which is what a plugin had to do when the host provided no library. Replacing them is a change of its own, not folded in here.

## [0.1.0] - 2026-10-16

- docs: `PLAN.md` -- three phases: display, then link to a Customer and store, then a Workflow.
- feat: backend -- billing accounts visible to the operator's `az login`, a tracked set, monthly actual and amortized cost by service and subscription from Cost Management, cached per month and never re-queried once settled.
- feat: analysis -- month-over-month trend, top services and subscriptions, anomalies against a three-month baseline, MACC / Azure Prepayment burn-down, forecast to year end (Azure's, or the run rate).
- feat: **Azure Cost** page with SVG charts -- monthly spend with forecast, spend mix by service or subscription, ranked bars, burn-down projection -- and a Settings page to choose the accounts.
