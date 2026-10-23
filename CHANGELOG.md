# CHANGELOG

All notable changes to the Azure Cost Manager plugin.

## [0.39.0] - 2026-10-23

- fix: **which services run in which subscription is kept** (operator, 2026-10-23: "dropping the services' attachment to subscription was a bad move and made us lose data"). Cost Management has always answered by service and subscription together; the sync kept the two apart and threw the pairing away to keep the cache small. Now every month keeps `pairs` (subscription -> service -> cost) under both actual and amortized cost, and the daily data keeps it per day.
  - **Refetched once:** every month synced before this is fetched again on the next sync, and an enrollment missing them is synced even if it was synced within the day. The daily data asks for its whole window once. The cache grows accordingly.
  - Nothing on screen reads the pairs yet; they are what drill-downs (a service to its subscriptions, a subscription to its services) will read.
- docs: 0.38.0 shipped 23 solution patterns, not 24.

## [0.38.0] - 2026-10-23

- feat: **Solutions**, for the Solution Sellers (operator, 2026-10-23: "Azure services don't map into solutions ... if the customer has this service, this means they might be building a data warehouse"). Rules first; Compass to come for what they cannot place.
  - **The footprint:** Sync tags now also reads, for the last three closed months, each subscription's cost by service, by meter subcategory and by resource group (three queries per enrollment, again only when another month closes).
  - **Patterns:** 24 shipped -- data lakehouse, data integration, streaming, operational databases, energy data (OSDU), GenAI application, Copilot Studio agents, ML platform, GPU, AI services, cloud-native, web apps, integration, DevOps, IoT, SAP, VMware (AVS), virtual desktop, network hub, backup and DR, SOC, security posture, and plain VMs when nothing else fits. Each requires services, meters or words in the subscription's and resource groups' names; supporting evidence or a telling name makes it *strong*, otherwise *likely*. Residue under $25 a month is ignored.
  - **Pitches:** each pattern names what to sell when the customer runs none of its missing piece anywhere (e.g. GenAI without AI Search: retrieval; with no Compass: sovereign inference on Compass by Core42).
  - **Per customer:** a **Solutions** tab (not in Customer view): solutions, what to pitch, and each subscription with its environment (from its names) and the evidence.
  - **All customers:** **Solutions, all customers** under Opportunities: by solution with the customers running it, every pitch, the largest subscriptions not placed; filter by solution play; **Export to Excel** (Solutions, Subscriptions, Pitches, Not Placed).
  - **Settings > Solution patterns:** the catalog as JSON, checked on save; it replaces the shipped one whole, and goes back with one click. It travels in the data export.
  - **Routes:** `GET /solutions`, `GET /customers/{id}/solutions`, `GET/PUT /solutions/catalog`, `GET /reports/solutions/export.xlsx`.

## [0.37.0] - 2026-10-23

- feat: **Move to another machine** (operator, 2026-10-23: "when I move this into another machine I would not need to sync everything again"). Settings has a new section:
  - **Export data** downloads one `.zip`: a manifest and every data file (customers and enrollments, the synced cache, FinOps prices, solution plays, Marketplace exclusions, the baseline and quota). The sync log stays behind; it records this machine's runs.
  - **Import** takes such a file and, after you tick that it replaces this machine's data, writes it in and reloads it without a restart. The next sync fetches only the delta since the export. A damaged, foreign or newer-format file imports nothing, and an import is refused while a sync runs.
  - MACCs kept on Customer notes move with the vault, not this file.
  - **Routes:** `GET /data/export.zip`, `POST /data/import`.

## [0.36.1] - 2026-10-22

- feat: **a quota period** (operator, 2026-10-22: "this year the quota was set for H2 only, July to December"). The quota is counted over a period you set (from and to month, up to 24 months) instead of always the fiscal year. It is named H1, H2, Q1–Q4 or CY when it is one (H2 2026), otherwise by its months. **Use the fiscal year** puts it back. The default baseline follows: the months before the period.

## [0.36.0] - 2026-10-22

- feat: **Baseline and quota** (operator, 2026-10-22: "a baseline, the last three months of consumption ... what's on top of that line is counted as revenue for me, part of my quota"):
  - **The baseline:** one for every customer, a start month and number of months averaged into a monthly line. The default is the three months before the fiscal year.
  - **What counts:** each fiscal-year month's consumption minus the line, counted **net** (a month under the line takes away). Closed months are actual; the current and later months use the automatic forecast, with the pipeline beside it.
  - **The figure counted** follows the report's filters: All (MACC consumed) or Core42's only (Core42 revenue), with credits subtracted or not.
  - **Your quota:** a total for the fiscal year (the year's first month is set, default July).
  - **Per customer:** a **Quota** tab with the baseline, above the line to date, projected and with pipeline, the year month by month against the line, and **Pipeline against what happened**: Open and Won opportunities' planned consumption for the closed months, against what the customer actually added. It is not shown in Customer view.
  - **All customers:** **Baseline and quota** (under the landing page's Quota and forecast) holds the settings, the attainment (to date, projected, with pipeline, gap to quota), every customer group, and the opportunities that missed their forecast. **Export to Excel** follows the filters (Quota, Missed Forecasts).
  - **Routes:** `GET/PUT /quota/settings`, `GET /quota`, `GET /customers/{id}/quota`, `GET /reports/quota/export.xlsx`.

## [0.35.0] - 2026-10-21

- feat: **Export to Excel on the five cross-customer reports** (operator, 2026-10-21: "the new reports don't have export; add it and maintain the templates"). Each is built on the plugin's workbook template (`export_reports`, on `export_xlsx`'s helpers): Aptos Narrow, a navy summary tab with KPI tiles, navy section bars, #D9E1F2 headers, `"$"#,##0` and `0.0%`, and a chart in column J. Values only.
  - **Growth and churn:** a summary with a chart of last month by customer, then Stopped and New, and By Solution Play.
  - **Service whitespace:** a summary, then Gaps (one row per customer and service).
  - **Marketplace whitespace:** by category with a chart, Leading Offers, and By Customer (a column per category).
  - **Subscription and tag hygiene:** a summary with tag coverage, then New and Dormant.
  - **Marketplace renewals:** by month expected, with a chart, then the Calendar.
  - **Route:** `GET /reports/{growth|whitespace|marketplace-whitespace|hygiene|renewals}/export.xlsx`. All five were opened in Excel with real data before release.

## [0.34.1] - 2026-10-21

- fix: Settings' customer list said "· on its Customer note" beside a customer with no signed value (for example "in DGE's MACC · on its Customer note"). It now says it only when there is a value on the note.

## [0.34.0] - 2026-10-21

- fix: **an affiliate that signs no MACC of its own no longer reads "No MACC set"** (operator, 2026-10-21: DGE's affiliates "written no MACC" while they have none of their own). When its parent's affiliates roll up into the parent's MACC, the customer list says **In DGE's MACC**. Its Overview says its consumption counts toward the parent's MACC, with a link to it, and Settings' customer list says the same. An affiliate of a parent whose affiliates sign their own (Mubadala) still reads No MACC set.
- change: **Settings has a side panel of sections**, as the Vault's settings do (operator: "the Settings page grows too much"). The sections are Customers, Enrollments in no customer, Solution plays and Sync. The section is kept in the page address, and editing a customer always opens Customers.
- change: **the reports are grouped by theme** (operator: "the reports need a different grouping"). The groups are Consumption and MACC, Opportunities, Marketplace, and Optimization and governance. Each card says whether it is about one customer or all customers.

## [0.33.1] - 2026-10-21

- fix: **Service whitespace** led with tiny customers. A crypto miner using no service at $500 a month showed 15 "gaps", Virtual Machines and Storage among them. It now lists the largest customers first and leaves out a customer that uses no service at that level yet.
- fix: **Marketplace categories.** "Oracle AI Database@Azure" read as AI & ML (it is a database, so now Data & Analytics), and an offer licensed "per VM" read as an OS image. Data is now checked before AI, and "VM" alone no longer means an image.
- fix: **Marketplace renewals** showed the plan twice when Azure's offer name already ends with it.

## [0.33.0] - 2026-10-21

Five reports across all customers (operator, 2026-10-21: "what else can we report on based on the data we have", picking 2, 4, 6, 11 and 12). All are built from data already synced, with no new Azure queries, and open from the landing page's "Across all customers".

- feat: **Growth and churn.** Each customer group's last three closed months against the three before, the last twelve against the twelve before, and last month year on year. Signals: growing or declining (20% either way over three months), a sharp drop (last month under half the three before), services that stopped ($1,000+ a month falling under a tenth) and new services. Each row opens on its solution plays' moves. Filters: All, Growing, Declining, Stopped or dropped.
- feat: **Service whitespace.** The services at least 30% of customers (and three or more) use at $500+ a month that a customer doesn't, most common first, by solution play, with what a typical user spends. Each gap has **Create opportunity**, with no consumption plan, as in This month. Marketplace and Unassigned spend are never proposed.
- feat: **Marketplace whitespace.** Marketplace bought from publishers other than Core42 or G42, by category (Security, Backup & DR, AI & ML, Data & Analytics, Networking, DevOps & Apps, OS & images, Other), each with its leading offers. Then by customer and billing profile, with the spend that counts toward the MACC and Core42's share of that customer's Marketplace. The category is read from the publisher's and offer's names.
- feat: **Subscription and tag hygiene.** Per customer group: subscriptions billed last month (and over 12 months), new ones, dormant ones, tiny ones (under $50), and the largest subscription's share, beside Environment, Project and Owner tag coverage.
- feat: **Marketplace renewals.** Every recurring Marketplace purchase's next expected charge and amount, with the cadence read from its charges (monthly, yearly or other; a single charge is taken as yearly). It flags renewals that are overdue. Filters: next 3 or 12 months, overdue, and optionally monthly subscriptions.
- fix: **the Marketplace solution play is the invoiced Marketplace on EA enrollments.** Cost Management leaves EA Marketplace out (ADNOC, September 2026: $28 against $373K invoiced), so a month's invoice figure stands for the play.

## [0.32.0] - 2026-10-21

- feat: **spend by solution play** (operator, 2026-10-21: "break services into solution plays: GPU is AI & ML, Databricks and Fabric are Data, VNET is Infra").
  - **The plays:** AI & ML, Data & Analytics, Infra, Security, App Innovation, Marketplace and Unassigned.
  - **The mapping:** a default covers all 116 services synced so far. GPU virtual machines (H100, A10 and other N-series, read from the meter detail) move from Infra to AI & ML, never more than the month's Virtual Machines cost.
  - **Where it shows:** a **By solution play** card on the Overview (the last 12 months stacked, and the last closed month by play with share and change), and **Solution plays** in Breakdown's Spend-by-month grouping.
  - **Settings:** a **Solution plays** section lists every service with its spend and play, to change one at a time or reset to the default, and flags services in no play. Your choices are kept in `Solution-Plays.json`.
  - **Routes:** `GET/PUT /solution-plays`, and `/consumption?group=play`.
- fix: Breakdown's Spend by month now follows the report's Enrollments choice, as the rest of the report does.

## [0.31.1] - 2026-10-21

- change: **the Billing date is out of the report's toolbar** (operator, 2026-10-21: "remove the billing date from the default view for now; it can be a billing report done separately", needing "all data, not only the current month"). It only decided when last month counted as closed, so before the 22nd it seemed to do nothing. The report reads calendar months again, and the workbook no longer mentions a billing date. A separate Billing report whose months run from the billing date across all history is planned in PLAN.md.

## [0.31.0] - 2026-10-21

- feat: **choose which enrollments a report shows** (operator, 2026-10-21: "for Mubadala I can't see Mubadala HQ ... the list of enrollments is too big to appear at the top without wrapping; let's select some of them to display their data").
  - **Picker:** the long line of enrollment names at the top of a report is now an **Enrollments: all 7 · 6 customers** picker. It's grouped by whose enrollment it is, with the customer's own first, so Mubadala's HQ (8990244) leads. Each enrollment shows its own short name rather than Azure's repeated "<parent>-<number>-" prefix. Quick choices are **All** and **Only <customer>'s own**.
  - **What follows the choice:** Overview, Forecast, Breakdown and the Excel export. The choice is kept in the URL (per customer), so a link reopens it.
  - **MACC consumed stays whole:** it always counts every enrollment that consumes the MACC, whichever are shown.
  - The other reports (Marketplace, FinOps, Tags, This month) still cover the whole group and show the enrollment count only.

## [0.30.0] - 2026-10-21

- feat: **Billing date** in the customer report's toolbar (operator, 2026-10-19/21). From this day of the month, the month before counts as closed. Before it, the report reads as of the day before: on 1–4 October, with the default billing date of the 5th, September is still the open month and August the latest closed one; from the 5th, September is final. Azure keeps adjusting a month's figures for about five days after it ends, so this keeps a not-yet-settled month out of the closed figures (latest month, MoM, YTD, run rate, forecast, MACC consumed).
  - **Setting:** choose any day from the 1st (calendar months) to the 28th. It's remembered in your browser like the Marketplace and credits filters.
  - **Export:** the Excel workbook follows it and says "as of … (billing date N)".
  - **Overview:** the open month's KPI is named, for example "Sep 2026 so far", and says it is still open.
  - **Not affected:** the daily This month report and the customer list.

## [0.29.3] - 2026-10-19

- change: **customer-friendly wording** (operator, 2026-10-19: "replace MACC burn with MACC consumed"). The screens and the Excel export no longer say "burn":
  - **Marketplace filter:** *All (MACC consumed)*.
  - **Customer list:** the column *MACC consumed vs term*.
  - **Overview:** *Consumption rate, 3-month average*, and runway "at the current consumption rate".
  - **Workbook:** *Consumption rate – 3-mo avg* and *Runway at current consumption rate*.
  - **Notes:** the report summaries, the Pipeline and Marketplace notes, and the Affiliates options say what counts toward the MACC consumed.

  Figures are unchanged.

## [0.29.2] - 2026-10-18

- fix: **a cut-off sync was sometimes not started again.** The resume looked only for a run that the current load had just closed as interrupted. When one load closed it and was itself reloaded before the resume fired (here: the plugin refused at load during the Plugin API 12 move, then installed again), the next load saw the run already closed and did nothing. It now starts again whenever the newest run was cut off by a restart within the last 12 hours, whichever load closed it.

## [0.29.1] - 2026-10-18

- chore: declares **Plugin API 12** (the framework moved 11 → 12 for `register_action` and `register_tag_namespace`, both additive). The host loads a plugin only on an exact match, so 0.29.0 was refused at load. This plugin uses neither new capability; nothing else changed.

## [0.29.0] - 2026-10-18

- feat: **affiliates either roll up into a parent's MACC or sign their own** (operator, 2026-10-18: "In Mubadala every affiliate signed their own MACC ... for DGE the affiliates don't sign a MACC on their own, so all data rolls up to DGE"). A parent's commitment has an **Affiliates** setting (Settings, a parent's signed value), stored on its Customer note as `macc_affiliates` (Entities 1.8):
  - **Roll up** (the default, as DGE): unchanged. The affiliates' consumption burns the parent's MACC, and an affiliate's own MACC is carved out of it.
  - **Own** (as Mubadala): only the parent's own enrollments burn its MACC, in the burn-down, the customer list's status and the workbook. Its totals, charts and exports still show the whole group. Each affiliate burns down its own MACC, and the carved-out allocation view does not apply.
  - The signed-value card says which rule applies. `azure-cost-manager.consumption`'s `customers()` gives each customer's `affiliates` rule, for Core42 Insight.
  - With Entities older than 1.8 the setting is kept out of the note write, which that version would refuse.

## [0.28.0] - 2026-10-18

- feat: **a sync cut off by a backend restart starts again by itself** (operator, 2026-10-18). When the plugin loads and the sync log shows the last run was interrupted, the same sync (Sync all, one customer, tags only or daily data only) starts again 20 seconds later, once the restart has settled. It resumes rather than restarts, since settled months, recently synced enrollments and stored days are never fetched again, and the log notes that it was started automatically. A run that finishes, or stops on an error, is never repeated. Neither is one cut off more than 10 times in a row before it asked Azure anything.

## [0.27.0] - 2026-10-18

- fix: **a dropped connection stopped the whole sync** (operator, 2026-10-18: "sync stopped: [WinError 10054] An existing connection was forcibly closed by the remote host"). A reset right after a throttle wait ended a Sync all at enrollment 26 of 38. A dropped connection or a timeout is now tried again after 2, 10 and 30 seconds; the sync log notes each retry. If the network stays down, that request fails like any Azure error, so the window is recorded as a problem and the sync moves on. Any other unexpected failure on one enrollment is also recorded and the sync goes on to the next. Only a lost `az login` still ends the run, since every enrollment after it would fail the same way.

## [0.26.0] - 2026-10-18

- perf: **Sync daily data fetches from a marker** (operator, 2026-10-18: "why no marker, and fetch only after that?"). Each enrollment remembers the last day it was fetched to. A refresh asks again only from 5 days before that day, because Azure keeps revising the latest days for that long, and keeps every earlier day as stored. Fetched through 18 October, the next refresh asks for 13 October onward instead of the whole month. Into a new month the window moves with it, and the last days of the month before are still asked again. Because a refresh is now this small, the 6-hour skip is gone and Sync daily data always brings the latest days.

## [0.25.0] - 2026-10-18

- perf: **the consumption cache is written less and smaller** (operator, 2026-10-18: "all Azure consumption is cached in one file, 26 MB and still counting -- is that okay?"). While a sync runs, the cache reaches the file at most every 30 seconds and whenever an enrollment finishes, instead of after every window and period; the page reads it in memory, so nothing waits. The file is compact JSON. Every save used to rewrite the whole ~27 MB file, which OneDrive then uploaded each time. A backend restart mid-sync now loses at most 30 seconds of fetched data, which the next sync fetches again. Needs the framework's atomic data writes (Second Brain, same day), so a write cut short can no longer leave a broken cache.

## [0.24.0] - 2026-10-18

- feat: **Sync tags** and **Sync daily data** buttons beside every Sync button (operator, 2026-10-18: "I can't see sync daily data and tags separately"). Each runs only its part, for one customer on its page or for every customer in Settings, without a full sync.
- fix: **Sync all looked like it fetched everything again** (operator, 2026-10-18). It didn't: of 112 enrollments, 59 synced within 20 hours were skipped, 21 fetched only their delta, and 32 had never been synced for cost (they had been synced only as billing profiles, invoice totals), so they needed their full history. But the progress counted all 112 and the full histories went first. The progress now counts only the enrollments that will be fetched, for consumption, tags and daily data, and the sync log notes how many were skipped.

## [0.23.0] - 2026-10-18

- feat: **Core42 revenue** (operator, 2026-10-18: "Core42 sees revenue from the MACC in total except Marketplace transactions that Core42 didn't create"). It is the MACC burn less Marketplace bought from any publisher other than Core42 or G42. The dashboard's Marketplace filter is now a choice of *All (MACC burn)*, *Core42's only (Core42 revenue)* or *None*, and the credits filter still applies to each. A customer's Overview gains a **Core42 revenue** KPI (all time and this year). The Excel workbook adds Core42 revenue to its summary and follows the filter. The `azure-cost-manager.consumption` service gives every month `core42_marketplace` and `core42_revenue`, and accepts `include_marketplace="core42"`. Core42's Marketplace is read from each month's Marketplace charges, so a month whose charges have not been fetched counts none.
- perf: **Refresh this month fetches only what is missing** (operator, 2026-10-18: "it gets everything, not only what we are missing; that's why it is very slow"). Enrollments never fetched by day go first. One fetched within the last 6 hours is skipped, and the sync log says so. Once last month has settled (five days after it ends), its days are kept and only this month is asked for, which roughly halves the pages on a large enrollment. ADNOC's main enrollment alone took 40+ pages and 15 throttle waits per refresh.
- change: **Marketplace and credits always count against the signed value.** The per-commitment switches (*Marketplace counts against it*, *Credits reduce what counts against it*) are gone, and the burn-down always counts usage plus all Marketplace, less credits. An offer marked as not eligible on the Marketplace report is still left out.

## [0.22.0] - 2026-10-18

- feat: **Sync activity log and Sync details** (operator, 2026-10-18: "I need to know why it gets stuck sometimes"). Every sync run is now logged to `Azure-Cost-Manager/Sync-Log.json`: each step, every Azure request and page with its status and duration, each throttle wait, each error. The last 12 runs are kept, with up to 1,500 events each. A run the backend stopped by restarting is closed as *interrupted* at the last thing it did. A folding **Sync details** panel under every Sync button shows how long the current step and the Azure request in flight have taken. It also lists the last runs (scope, duration, outcome, requests, pages, throttle waits, errors); open one to read its events. `GET /sync` gains `step_started_at` and `in_flight`; new routes are `GET /sync/log` and `GET /sync/log/{run_id|latest}`.
- fix: a Refresh this month that finds no enrollments for the customer now says so as a sync problem, instead of ending "0 of 0" without a word.
- fix: a throttle wait's `waiting_seconds` stayed on the status after the wait ended, so the banner kept saying Azure asked to wait.

## [0.21.0] - 2026-10-18

- feat: **This month by tag, one grouping at a time** (operator, 2026-10-18: "see the tags … per Project, Owner, Environment; massive scrolling because of the number of resource groups"). Refresh this month also fetches the day-by-day cost per Project, Owner and Environment tag (the enrollment's own spelling of each key; values folded as in the Tags report, untagged left out). The page shows one grouping at a time (Service, Subscription, Resource group, Project, Owner, Environment), each with its count of new items, filtered to All, New this month or Growing; it lists the first 15 rows with "Show all" for the rest; and the chart and the table fold away. The New this month figure is split by kind.
- fix: **Last month looked smaller than it was** (operator: "$4,223,152 last month but it was almost 5.9"). A refresh cut off part-way had fetched only one of a customer's enrollments, and every figure added up only the ones fetched without saying so. The page now names the enrollments not fetched by day yet and warns that their spend is missing.

## [0.20.1] - 2026-10-18

- fix: **"This page stopped working" while a Refresh this month ran** (operator, 2026-10-18). The sync banner formatted a month range every stage had to report; the this-month, tags and pricing stages report none, so the banner threw and took the whole page down. It now names each stage (this month by day, tags, pricing, amortized meters, balances, Marketplace), shows months only when there are some, and the status type says which fields a stage may leave out, so the compiler checks it.

## [0.20.0] - 2026-10-18

- feat: **This month** (operator, 2026-10-18: "know what is changing in the customer tenant so I can see any missing opp and track it early"). A report per customer from daily figures fetched only on demand (**Refresh this month**: last month and this one, by service and subscription, and by resource group -- two Cost Management queries per enrollment). Month to date against the same days last month, the projected month end, a day-by-day chart, and every workload new this month -- a service, subscription or resource group billed now and not at all last month (nor, for a service or subscription, in the three months before) -- each with **Create opportunity** (no consumption plan). The fastest-growing of each against last month's pace. Azure's daily data lags a day or two; the report says to which day. The FinOps digest gains "New this month" for customers whose month has been refreshed.

## [0.19.2] - 2026-10-18

- perf: the `azure-cost-manager.consumption` service listed every customer twice per `monthly_of` call; a page asking for 99 customers' months paid ~200 listings. It now reuses one listing for ten seconds and hands the customer record straight to the calculation.

## [0.19.1] - 2026-10-18

- perf: **the customer list took 9-15 s once every customer had a note.** Each listing read all 99 MACCs from their notes through Entities, and each read scans the vault index; Core42 Insight, which lists customers many times, took 38 s (operator: the Insight report "takes forever to load"). Note reads are now cached for a minute; a save here updates the cache at once, and an edit in Obsidian shows within the minute.

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
