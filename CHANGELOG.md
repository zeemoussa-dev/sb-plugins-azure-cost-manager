# CHANGELOG

All notable changes to the Azure Cost Manager plugin.

## [0.19.0] - 2026-10-18

- feat: `azure-cost-manager.consumption` gains `customers()` -- every customer here, linked to a note or not (id, name, parent_id, customer_stem or None, currency, route) -- and `monthly_of(customer_id, ...)`, `monthly()`'s exact shape by Cost Manager id. For Core42 Insight, where a parent's terms cover affiliates that have no note of their own (operator, 2026-10-18). `linked()` and `monthly()` are unchanged.

## [0.18.0] - 2026-10-18

- feat: **a customer can be linked to a Partner note** (operator, 2026-10-18: "Link Partner notes"; Entities 1.5). The link pickers in Settings and the Pipeline tab list Customers and Partners, each with its affiliates at any depth, from Entities' `hubs()` (`customers()` before 1.5); the signed value, the pipeline and the Entities cost panel work for a Partner note the same way. The G42 family can now be linked when it is set up.

## [0.17.0] - 2026-10-18

- feat: **the `azure-cost-manager.consumption` service**, for Core42 Insight, which bills on consumption. `linked()` lists every customer linked to a Customer note (its stem, name, parent's stem, currency, route); `monthly(stem, include_marketplace, subtract_credits)` gives that customer's OWN enrollments by month (a parent without its affiliates) -- usage, Marketplace, credits, the total under the two switches, and whether the month is closed -- with a forecast at the burn-down's run rate to the MACC term's end (or the year's end), and the commitment. Local data only; two customers on one note: the top-level one answers, as in `for_entity`.

## [0.16.1] - 2026-10-17

- perf: **the customer list copied every enrollment's synced months to read two fields.** Each listing deep-copied all enrollments (131 JSON round-trips of a 15 MB cache on this install) for `synced_at` and `errors`; `account_status` reads them in place. `for_entity` went from 1.2 s to 0.01 s for a small customer (reported by the Entities session), and every page that lists customers is faster.

## [0.16.0] - 2026-10-17

- feat: **the `azure-cost-manager.portfolio` service** (asked for by the Entities "Customers & Partners" work, 2026-10-17: the operator chose to show Cost Manager data on a Customer's page through a service). `for_entity(customer_stem)` returns the portfolio row of the customer linked to that Customer (or affiliate) note -- signed, burn, last month, trend, status, sync state -- plus `route`, the customer's page here; None when nothing is linked to the note. Local data only, never Azure: a page load asks it. `portfolio(only=...)` computes one customer.

## [0.15.0] - 2026-10-17

- feat: **Enrollments in no customer** in Settings (operator, 2026-10-17: "Where can I see Enrollement not Assigned to Customer"). Every billing account the sign-in sees that belongs to no customer, grouped like the editor's suggestions (a renewal, or linked under one parent), with last month's and the last twelve months' spend from the light sync of billing profiles -- no Azure call -- the biggest first, searchable. **Create customer** opens the editor with the group's name and enrollments filled in. `GET /unassigned`.

## [0.14.3] - 2026-10-17

- fix: **a restarted sync redid every enrollment** (operator, 2026-10-17: "it should sync the ones that didn't sync yet and add the delta for the rest every week or when I click sync"). A sync of everyone now takes never-synced enrollments first, then the longest ago, and skips one synced in the last 20 hours -- for consumption and for tags alike -- so a restart resumes where it stopped. The weekly job and Sync all still bring every enrollment's delta (settled months were already never fetched again); syncing one customer always refreshes it.

## [0.14.2] - 2026-10-17

- fix: **the billing accounts disappeared and no customer could be linked** (operator, 2026-10-17). While the backend restarts -- a plugin install, a framework change -- the plugin's routes answer 404 for a few seconds, and Settings fetched the billing accounts once and kept the empty result. It now tries again after 3, 10, 30 and 60 seconds and has **Try again**. On the backend, an hourly refresh of the account list that fails keeps the last good list and retries in five minutes, so saving a customer never depends on that one call; and the sync and the pages no longer run two `az` token requests at once.

## [0.14.1] - 2026-10-17

- fix: on the first real customer, Business unit showed 9,818 values: the tag key `revision` is two edits from "division" and holds timestamps. A typo must now start with the same letter as the name it misspells, a stored key is judged by today's rules, values that cost nothing are left out, and `npr`/`nprd` fold to Non-production.

## [0.14.0] - 2026-10-17

- feat: **reports by tag** (operator, 2026-10-17: "find Tags and Build some Reports Against the Tags"). Six business dimensions -- Environment, Project, Application, Business unit, Owner, Cost centre -- found among each enrollment's tag keys by spelling (case, spaces, `_`, an `x_` prefix and small typos ignored: `environemnt`, `pojectname`, `buisnessunit`), values folded (prd/prod/production → Production). A new sync stage lists each enrollment's tag keys (Consumption API, weekly) and queries Cost Management once per spelling it uses -- at most four per dimension, the last six closed months and the current one, settled months never again; **Sync tags** runs it alone. A **Tags** report per customer (values by month, coverage, untagged spend, and the spellings found -- tag hygiene), **Tag coverage** across customers, and a **Tags** sheet in both workbooks. Untagged is the month's total less what any spelling tagged.
- fix: a burst of price queries met the price list's rate limit (429); it now waits and tries again.

## [0.13.0] - 2026-10-17

- feat: **FinOps phase F2 -- savings in dollars.** Each steady VM or GPU candidate is priced from Azure's public **Retail Prices API** (no sign-in, not Cost Management): a 1- and 3-year savings plan and reservation, as the average discount across the series' sizes in the pricing region (`uaenorth` unless set through `PUT /finops/pricing-region`). A reservation's term price is spread over its hours; a Windows meter saves on compute only. The meter subcategory is found in the price list by its series ("Dlsv5 Series Linux" is "Dlsv5 Series", "Dv3/DSv3" either half, "NVadsA10_v5" is "NVadsA10v5 Series"). Prices are cached in `FinOps.json` and refreshed monthly by the sync after customers, or at once from **Price candidates now**. Databases, storage and capacities are listed but not priced yet.
- feat: **Create opportunity** on a candidate (My view): an Opportunity under the linked Customer note, titled with the finding and its saving, **without a consumption plan**, so a saving never inflates the pipeline forecast.
- feat: `GET /finops/digest`: the week's FinOps as text -- the largest savings and who is over budget -- for a Hermes job to send.
- The FinOps report, Optimization opportunities and the FinOps sheet show the savings per option and in total.

## [0.12.1] - 2026-10-17

- fix: FinOps money for a customer whose data came through the Consumption API read "1,803,971 USD" instead of "$1,803,971": its padded currency code ("USD  ") is trimmed, as the portfolio already does.

## [0.12.0] - 2026-10-17

- feat: **FinOps, phase F1** (operator, 2026-10-17; plan in `PLAN.md`). A **FinOps** report per customer: commitment coverage by month and by family (virtual machines, GPUs, Azure OpenAI, and anything the customer has reserved), steady on-demand candidates (on demand in each of the last six closed months, at least $1,000 a month, varying no more than 25%), commitments bought up front, the fastest-growing services and subscriptions, and the monthly budget -- the MACC spread over its term unless overridden in Settings. **Optimization opportunities** across customers ranks every customer by steady on-demand spend, with coverage and budget status. Both workbooks gain a **FinOps** sheet.
- feat: **My view / Customer view** on every customer report (operator: "Different Views One for me one for the Customer"). The Customer view leaves out only the forecast scenarios (operator's choice), on the server; its export, "Export for the customer", has no scenarios sheet. Sync and Edit are hidden while it is on, for screen-sharing.
- feat: the sync fetches the meter detail once more, amortized, for the last 13 months: under actual cost a reservation's usage costs nothing, so coverage needs it. One or two queries per enrollment, once; settled months are not fetched again.
- Azure's catch-all meter subcategory "Unassigned" is never a candidate, and database compute that names a VM series is not counted as a VM.

## [0.11.0] - 2026-10-17

- feat: **a PivotTable in the Marketplace export** (operator, 2026-10-17: "a Pivot Table with Each Publisher, What Solution Who Purchased and When with the Amount"; chose a real Excel PivotTable). The cross-customer workbook's second sheet, **Pivot**, is an Excel PivotTable -- Publisher › Solution › Buyer down the side, months across, Sum of Amount, filters for Group, Buyer type and Toward MACC -- over a new **Marketplace data** sheet, one row per solution, plan, buyer and month. Excel builds it when the file opens (`refreshOnLoad`); a previewer shows it empty. Spellings that differ only in case are made one (Azure bills "CommVault" and "Commvault", "Pay-As-You-Go" and "Pay-as-you-go"): Excel compares pivot items ignoring case, and a cache holding both does not open at all. Checked in Excel against this install's data: 5,724 lines, grand total equal to the report's to the cent. `backend/xlsx_pivot.py` builds the pivot from openpyxl's pivot parts; the page's `/marketplace` response leaves the lines out.

## [0.10.1] - 2026-10-17

- fix: **the move of signed values onto Customer notes gave up after one failed try.** Installing Entities 1.3.0 restarts the backend, and right after a restart the vault index is empty, so every Customer note read as missing; the move kept the values here but marked itself done, and every linked customer then read its (empty) note and showed no MACC. The move now counts as done only once every value has moved, and a value not moved yet is the one that counts.

## [0.10.0] - 2026-10-17

- chore: **framework_api 11, and the framework's breadcrumbs** (operator, 2026-10-17: "Shouldn't it be Breadcrumb and Have a Standard around that" -- chose a framework standard, ADR-042). Every page past the landing page renders the host's `Breadcrumbs` (`Azure Cost › Consumption overview › Mubadala › Masdar`); the plugin's own trail and its `.azure-cost-breadcrumb` styles are gone. Links into Settings are built with the host's `pluginSettingsLink` (the customer's or report's name as the origin), the host renders the Settings trail (`Azure Cost › ADNOC › Azure Cost Manager`), and Save or Cancel returns through `usePluginReturn`, which validates the way back with the same rule that decides which routes the plugin may mount. `settingsLink`'s own `safeBack` and the Settings page's back link are removed.

## [0.9.0] - 2026-10-17

- feat: **a linked customer's signed value lives on its Customer note** (operator, 2026-10-17: "Where does the MACC data being stored in the md vault" -- chose the Customer note as the single source of truth). With Entities 1.3 or later, the MACC of a customer linked to its Customer note is read from and saved to that note's `macc_*` properties (`entities.customers` `commitment` / `set_commitment`), so it can be edited in Obsidian too and the vault can answer about it. On first use, a value held in this plugin's data moves to its note, unless the note already has one, which wins; linking to a note that has one keeps the note's. A value left incomplete in Obsidian counts nothing and Settings says why; a missing note is reported. Unlinked customers, or an Entities older than 1.3, keep it in this plugin's data as before. The sync reads term starts the same way. Settings says where each value lives.

## [0.8.3] - 2026-10-17

- fix: **Settings leads back** (operator, 2026-10-17: editing a MACC went to Settings with no way back). Every link into Settings carries where it came from: Settings shows "← Back to the report" (or "Open Azure Cost" when opened from the menu), and a customer opened from a report returns to that report on Save or Cancel. A customer's report has an "Edit … MACC, enrollments" button that opens its editor directly. Only this plugin's pages are accepted as a way back.

## [0.8.2] - 2026-10-17

- fix: a customer never synced said "Not synced" and "Synced Never"; the status alone says it now.

## [0.8.1] - 2026-10-17

- fix: a group with some affiliates still syncing showed "Not synced" and nothing else. It now shows what is synced, dated by its oldest synced enrollment, and says how many enrollments are not synced yet.
- fix: money for billing-profile customers read "8,827,323 USD" instead of "$8.8M": the Consumption API pads its currency code ("USD  "). The portfolio trims it.

## [0.8.0] - 2026-10-17

- feat: **the customer list is a portfolio** (operator, 2026-10-17: a better view for the customer list, with affiliates that collapse). Each row shows the signed MACC, a burn bar against the share of the term elapsed, the last closed month and its change, a six-month trend line, where the burn lands (exhausts in a month, or short by an amount at term end) and a status -- Behind, Exhausts early (three months or more before the term ends), On track, Consumed, No MACC set, Not synced. A group's row rolls up its affiliates, as its report does, and its affiliates fold under it: collapsed by default, one click per group or Expand all / Collapse all, remembered per browser; a search or a status filter opens the groups it matches in. Columns sort; filters are in the URL. All from local data through one new call, `GET /portfolio` -- opening the list never queries Azure.

## [0.7.0] - 2026-10-17

- feat: **reports first, then the customer** (operator, 2026-10-17: the landing page shows the reports; a report opens a list of customers and affiliates; a customer opens the report). `/azure-cost-manager` is now a catalogue of reports -- Overview, Forecast, Pipeline, Marketplace and Breakdown per customer, and Marketplace across all customers. A per-customer report at `/azure-cost-manager/report?report=…` lists every customer with its affiliates under it (signed MACC, enrollments, last synced, searchable); choosing one opens the report, with a breadcrumb back and the other reports one click away. Links from 0.6 (`?customer=&tab=`) still land on the same report.

## [0.6.0] - 2026-10-17

- feat: **every billing profile, not just customers** (operator, 2026-10-17: the Marketplace report needs every customer that signed with the partner). "Sync all billing profiles" (and `POST /sync?profiles=only|also`) syncs each billing profile that is in no customer, one at a time from its term start, **lightly**: each month's invoice totals and Marketplace charges, through the Consumption API -- not Cost Management, whose per-sign-in throttling would make 135 profiles take days. The cross-customer Marketplace lists them beside customers, grouped the way Settings suggests and marked "not a customer yet", with each buyer's consumption and Marketplace share. The weekly job should call `?profiles=also`.
- change: removing a customer no longer deletes its synced data. Its accounts drop back to billing profiles: the Cost Management breakdowns go, the invoice totals and Marketplace charges stay.

## [0.5.1] - 2026-10-17

- fix: **the exported charts now take the operator's workbook colours** (operator, 2026-10-17: "The Report Charts Colors are Not Matching the Template"). Every chart colours its series from the workbook theme, and openpyxl writes the 2007 Office theme (Calibri; #4F81BD, #C0504D …) while the operator's workbook is on the current one (Aptos; #156082, #E97132, #196B24, #0F9ED5 …). Both exports now carry that theme (`backend/office_theme.py`, Excel's stock theme, no content of its own).
- feat: **Marketplace from the start** (operator: "see all the Marketplace from start till now"). The period picker's last option is "From the start": everything synced, and the report names the first month it actually has data for instead of an invented date. A customer workbook's Marketplace sheet always runs from the start.

## [0.5.0] - 2026-10-17

- feat: **Marketplace** (operator, 2026-10-17: Marketplace consumption per customer, which partner solutions they bought, and what it gives in all MACCs). The sync reads each EA billing period's Marketplace charges -- publisher, offer, plan, subscription, metered or SaaS -- which Cost Management cannot name at this scope; they match the invoiced Marketplace, and a month that does not is reported. Every Marketplace dollar counts toward the MACC unless its offer is marked not eligible (Azure does not say which are); one switch per offer, for every customer, and the burn-downs respect it. A **Marketplace tab** per customer (solutions bought, by month and publisher, toward MACC or not, and solutions adopted at no charge -- free plans, trials, models billed elsewhere), a **Marketplace page across all customers** (each partner solution, who bought it, revenue and MACC-counted revenue, by publisher, customer and month; a group's affiliates are not double-counted), a Marketplace sheet in each customer's workbook, and a cross-customer Marketplace workbook.
- feat: the selected customer and tab are in the URL, and the Marketplace page's filters too, so a refresh or a shared link lands where you were; the Marketplace/credits switches are remembered per browser (framework API 10's `pluginHost/state`).

## [0.4.1] - 2026-10-17

- chore: `framework_api` 10 (made by the framework's session; recorded here).

## [0.4.0] - 2026-10-17

- feat: **groups -- a parent's MACC carved out to affiliates** (operator, 2026-10-17: the parent signs a MACC, say $50M; an affiliate signs its own, say $7M, which deducts from the $50M, with its own allocation). A customer can be an affiliate of another (one level deep). The parent's page rolls up its own and its affiliates' enrollments against the group's MACC and adds a **MACC allocation** card -- each affiliate's signed MACC, consumption, pace and projection; the unallocated rest against the parent's own enrollments; the group total; over-allocation flagged. An affiliate's page is its own, with a banner naming the group. Syncing a parent syncs its affiliates, back to the parent's MACC start. Settings sets the group; the picker and the customer list show affiliates under their parent. The export's Dashboard gains a MACC Allocation section, and a parent's Export sheet covers every enrollment in the group.
- feat: an affiliate the vault does not know yet can have its **affiliate note created** from the Pipeline tab, by the Entities plugin (needs Entities 1.2's `create_affiliate`; until then the button says so).

## [0.3.4] - 2026-10-16

- feat: **the export is laid out and styled like the operator's own workbook** (operator, 2026-10-16: "The Formatting of the Exported Excel is not the Same"). Sheets in its order -- Dashboard, Forecast Auto, Forecast Scenarios, Pipeline, Export -- then Services, Subscriptions, GPU & AI, Commitment and Credits. Its look: Aptos Narrow, no gridlines, navy section bars and tab, light-blue KPI tiles across merged column pairs, peach tiles and a side block for the signed value, `#D9E1F2` table headers, thin grey borders, `"$"#,##0` money, real `0.0%` percentages and `yyyy-mm` month dates, charts stacked in column J beside their tables with labels where they fit. The Pipeline is its month grid under a merged year header with banded rows and a navy total, a block per year; the Export is one block per billing profile and year, Total row first, with GPU H100 / H200 / other and PTU split out of Azure so the columns add up to the total.

## [0.3.3] - 2026-10-16

- fix: **the Sync button looked like it did nothing** (operator, 2026-10-16). It started the sync, but the only sign was a line of grey text, and the page did not change until the whole sync ended -- minutes, since every billing month is its own call and Azure throttles. A sync now shows a banner with the customer, the enrollment and step it is on, any wait Azure asked for, and a progress bar; the page refreshes as each enrollment finishes; and a click while another sync runs says which one, instead of a silent no.

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
