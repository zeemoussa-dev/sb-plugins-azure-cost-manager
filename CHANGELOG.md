# CHANGELOG

All notable changes to the Azure Cost Manager plugin.

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
