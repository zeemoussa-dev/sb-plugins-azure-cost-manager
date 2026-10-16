# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this repository is

**The Azure Cost Manager plugin** for Second Brain (`ADR-022`): customers'
Azure agreements (EA, MCA/MACC) and their monthly consumption, read from Azure
Cost Management with the operator's own `az login`, analysed and charted. A
backend mounted at `/plugins/azure-cost-manager/`, an **Azure Cost** screen and
a Settings page. `PLAN.md` holds the three phases and the decisions behind them.

## Boundaries

- **Nothing is written to the vault yet.** Consumption lives in the plugin's
  local data until a customer is linked to an Entities Customer (Phase 2).
- **Pages never query Azure.** Only the background sync does (`POST /sync`):
  Cost Management throttles per sign-in, and a page view must not spend it.
- **The operator's own sign-in, never a stored secret.** The backend borrows
  `az account get-access-token`; it sees what the operator sees in the portal.
- **A plugin imports only `app.plugin_api`.** Nothing else from the framework may
  be imported, and no framework file copied in. Screens import only their own
  files, `src/pluginHost/`, React / react-router and the host's `echarts` /
  `echarts-for-react` (framework_api 8). Import `echarts/core` and only the
  pieces a chart draws (`ui/charts.tsx`), never the whole `echarts` package.
- **A missing framework capability is logged in the framework repository** and
  fixed there. Installing a Workflow from this plugin (Phase 3) is one.
- **Opportunity notes belong to the Entities plugin.** This plugin reads and
  writes them only through `entities.opportunities` (contract in `PLAN.md`),
  asked for at call time; it never writes those files itself.
- **Never query a settled month twice.** Cost Management throttles per sign-in.

## Layout

| Path | Holds |
|---|---|
| `plugin.json` | id, version, `framework_api`, what it requires |
| `backend/azure_token.py` | the token from `az` |
| `backend/billing_client.py` | the Azure calls, raw rows only |
| `backend/consumption_store.py` | the local data: customers, and per-account monthly spend maps |
| `backend/customers.py` | customers as groups of enrollments, their signed value, related-enrollment suggestions |
| `backend/consumption_sync.py` | the background sync from Azure into local data |
| `backend/consumption_analysis.py` | pure analysis: merge and measures, trend, breakdowns, anomalies, burn-down |
| `backend/categories.py` | GPU by SKU, Azure OpenAI PTU vs tokens, from meter detail |
| `backend/forecasting.py` | the automatic trend × seasonality forecast, and the scenarios |
| `backend/dashboard.py` | the operator's workbook KPIs and chart series |
| `backend/pipeline.py` | the customer's Opportunity notes, through the Entities plugin's `entities.opportunities` service |
| `backend/export_xlsx.py` | the per-customer Excel workbook (host `openpyxl`) |
| `backend/consumption_service.py` | answering for a customer from local data |
| `backend/routes.py` | the HTTP surface |
| `ui/` | the Azure Cost page (Overview, Forecast, Pipeline, Breakdown tabs), its charts, the sync control, Settings |
| `tests/` | the backend's tests, against a fake Plugin API and a mock Azure |

## Commands

| Command | Where |
|---|---|
| `python -m pytest` | repository root, with a Python that has `httpx` and `fastapi` (the framework's venv does) |
| `<second-brain>/src/backend/.venv/Scripts/python.exe <second-brain>/src/backend/scripts/publish_plugin.py . --dry-run` | every publish gate, nothing written |

## Rules

- Read before writing; minimal changes; separate commits per logical change;
  never force-push `main`.
- Update `CHANGELOG.md` for everything created or changed.
- Never put a customer's name, billing account id or figures in this repository.
- Add inline comments only where the WHY is non-obvious.
