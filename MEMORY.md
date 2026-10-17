# MEMORY.md

Decisions, patterns and constraints for the Azure Cost Manager plugin. This file
describes only this repository (`ADR-023`).

Format: `- **[date] Rule.** Reason.` Append; correct an entry by superseding it.

## Decisions

- **[2026-10-16] Azure Cost Management API, signed in with the operator's `az login`.** No secret stored; the plugin sees exactly the billing accounts the operator sees in the portal, and an expired sign-in is reported, not retried.
- **[2026-10-16] Display first, store later.** Phase 1 only shows consumption. Vault notes and raw data are written once a billing account is linked to an Entities Customer (Phase 2), because Azure's account name often differs from the Customer's.
- **[2026-10-16] Vault notes will be written directly**, as `sb-plugins-action-center` does -- the Plugin API has no vault write (operator's choice over adding one).
- **[2026-10-16] Questions are answered through an ADR-032 Workflow** installed from this plugin's Settings: an `.sbf` through the framework's artifact import for now, a Plugin API layer for Hermes content later.

- **[2026-10-16] A customer is a group of enrollments, synced into local data weekly.** One enrollment per customer was wrong on first contact: one customer was a parent plus two linked enrollments, and another's consumption moved to a new enrollment mid-year, so the old one read zero. Pages read local data only; a weekly Hermes cron job calls the sync route. *Supersedes the display-only, refresh-on-open model of 0.1.x.*
- **[2026-10-16] The signed value is entered by the operator.** Indirect EA shows no prepayment and the commitment lots answer 401 to a partner's sign-in, so Azure cannot say what the customer signed for.

- **[2026-10-17] An affiliate's MACC is carved out of its parent's.** A group signs one MACC; each affiliate signs its own fixed MACC that counts against the parent's, and every affiliate dollar burns both. Modelled as parent and affiliate customers, one level deep; the parent rolls everything up and shows allocated, unallocated and over-allocated.

- **[2026-10-17] Every billing profile is synced lightly; customers fully.** The Marketplace report has to cover every buyer, so profiles in no customer get each month's invoice totals and Marketplace charges through the Consumption API, never Cost Management (its per-sign-in throttling makes 135 profiles a matter of days). A profile that leaves a customer keeps those, and loses only the breakdowns.

- **[2026-10-17] Reports first, then the customer.** The landing page is a catalogue of reports; a per-customer report asks for the customer (groups with their affiliates under them) before it shows anything. Operator's navigation, over the 0.6 single page with a customer picker. Old `?customer=&tab=` links redirect.

- **[2026-10-17] A linked customer's signed value lives on its Customer note** (`macc_*` properties, through `entities.customers` `commitment`/`set_commitment`, Entities 1.3+). The operator chose the vault as its single source of truth, so it is editable in Obsidian and visible to the vault. This plugin's data keeps it only for unlinked customers or an older Entities; a note that has one always wins over a value held here. *Supersedes, for linked customers, "the signed value is entered by the operator" being stored here.*

- **[2026-10-17] FinOps findings are one engine with two views.** The Customer view filters the same analysis on the server (today: no forecast scenarios), never a second analysis and never a browser-side hide, so the two cannot disagree and an export cannot leak what the view leaves out.

## Patterns

- **[2026-10-16] The current month is never evidence.** It is partial: no month-over-month change, no run rate, no anomaly is computed from it.
- **[2026-10-16] An anomaly must be sharp and material**: at least 50% off its trailing three-month baseline and at least 2% of the month's total.
- **[2026-10-16] Charts are SVG drawn in the plugin.** The host has no chart library, and a screen may not bring one. *Superseded below.*
- **[2026-10-16] Charts are the host's `echarts`, imported piece by piece** (framework_api 8, `ADR-039`): `echarts/core` plus the chart types and components used, through `echarts-for-react/esm/core`. A canvas cannot resolve CSS variables, so colours are read from the stylesheet when a chart renders.

- **[2026-10-17] A link into Settings carries `back`** (`settingsLink`). Settings lives under the framework's `/settings`, outside this plugin's pages, so without it the operator had no way back; `safeBack` accepts only this plugin's own paths. *Superseded below.*
- **[2026-10-17] Trails and the way back are the framework's** (API 11, ADR-042): `Breadcrumbs`, `pluginSettingsLink` and `usePluginReturn` from `pluginHost/breadcrumbs`. Never validate a `back` path here -- the host checks it with the same rule that decides which routes the plugin may mount. The host renders the Settings trail; the Settings page draws none.

## Constraints

- **[2026-10-16] A Cost Management query covers at most a year**; history is twelve months.
- **[2026-10-16] Cost Management throttles per sign-in, not only per scope.** After a few refreshes, an enrollment nothing had touched answered 429. Never query Azure from a page view; only the sync does.
- **[2026-10-16] A refresh waits out throttling of up to a minute.** Each twelve-month query costs about twelve query units of the scope's budget, so a refresh's second query is routinely throttled 15-45 seconds on a large EA enrollment. A shorter inline limit made every first refresh fail.
- **[2026-10-16] Billing accounts are listed on API `2020-05-01`, never newer.** For a partner's sign-in on indirect EA, `2021-10-01` onwards list none of the enrollments (0 against 135, `includeAll` makes no difference). Cost Management, forecast and balances work on current versions at the same scope.
- **[2026-10-16] Import the chart wrapper from `echarts-for-react/esm/core`, never `lib/core`.** `lib/` is CommonJS; under the Vite dev server its default import is the module object and React fails with "Element type is invalid". The publish gate builds but never renders, so only opening the page catches it.
- **[2026-10-16] Through `az.cmd`, an `&` in a URL is eaten by cmd.** When probing Azure by hand, pass query parameters with `az rest --url-parameters`, not in `--url`.
- **[2026-10-16] A month is settled five days after it ends**; until then it is fetched again on refresh, after that never.
- **[2026-10-16] `az` must be on the backend's PATH and signed in as the operator.** A backend run as a service account would not see the operator's billing accounts.
- **[2026-10-17] The Consumption API pads its currency code** (`"USD  "`). Trim it before it reaches `Intl.NumberFormat`, which rejects it and falls back to raw digits.
- **[2026-10-17] Installing a backend change interrupts a running sync.** The plugin's backend loads only when the framework's backend reloads, and the reload stops the sync thread. Settled months survive, so start the sync again afterwards; a UI-only change needs just the frontend dev server restarted.
- **[2026-10-17] Right after a backend restart the vault index is empty.** Every Customer note reads as missing for a few seconds. Anything done once per run against notes must retry until it succeeds, never mark itself done on a failure.
- **[2026-10-17] Excel compares PivotTable items ignoring case.** A pivot cache holding "CommVault" and "Commvault" makes the whole workbook fail to open (`Workbooks.Open` fails, no repair offered). Fold every text field with `xlsx_pivot.fold_case` before writing a pivot's data. Check a generated pivot by opening it in Excel through COM; openpyxl will write a broken one without complaint.
- **[2026-10-17] Coverage is read from amortized meters; candidates from actual.** Under actual cost a reservation's usage costs nothing and its purchase lands in one month, so coverage needs `AmortizedCost`. On-demand costs the same either way, so steady candidates read the full actual history. Azure's `Unassigned` meter subcategory is a catch-all, never a candidate.
