# Azure Cost Manager — a Second Brain plugin

Customers' Azure agreements and monthly consumption, read from Azure Cost
Management with your own `az login`:

- **Monthly spend** — actual and amortized, month over month, with the rest of
  the year's forecast.
- **Spend mix** — each month split by service or by subscription.
- **Top services and subscriptions** — last month, with share and change.
- **Anomalies** — services that spiked, dropped or appeared against their last
  three months.
- **Commitment** — MACC burn-down (MCA) or Azure Prepayment balance (EA), with
  the projected run-out and any shortfall at term end.

## Using it

1. `az login` on the machine running the Second Brain backend, as an account with
   Billing Reader (or better) on the customers' billing accounts.
2. Install the plugin from Settings → Marketplace → **Install from a repository**,
   and restart the backend.
3. Settings → Plugins → **Azure Cost Manager**: tick the billing accounts to follow.
4. Open **Azure Cost** in the sidebar.

Phase 1 displays only. Linking an account to a Customer and storing the data in
the vault is Phase 2; asking questions through a Workflow is Phase 3 — see
`PLAN.md`.
