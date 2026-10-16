# MEMORY.md

Decisions, patterns and constraints for the Azure Cost Manager plugin. This file
describes only this repository (`ADR-023`).

Format: `- **[date] Rule.** Reason.` Append; correct an entry by superseding it.

## Decisions

- **[2026-10-16] Azure Cost Management API, signed in with the operator's `az login`.** No secret stored; the plugin sees exactly the billing accounts the operator sees in the portal, and an expired sign-in is reported, not retried.
- **[2026-10-16] Display first, store later.** Phase 1 only shows consumption. Vault notes and raw data are written once a billing account is linked to an Entities Customer (Phase 2), because Azure's account name often differs from the Customer's.
- **[2026-10-16] Vault notes will be written directly**, as `sb-plugins-action-center` does -- the Plugin API has no vault write (operator's choice over adding one).
- **[2026-10-16] Questions are answered through an ADR-032 Workflow** installed from this plugin's Settings: an `.sbf` through the framework's artifact import for now, a Plugin API layer for Hermes content later.

## Patterns

- **[2026-10-16] The current month is never evidence.** It is partial: no month-over-month change, no run rate, no anomaly is computed from it.
- **[2026-10-16] An anomaly must be sharp and material**: at least 50% off its trailing three-month baseline and at least 2% of the month's total.
- **[2026-10-16] Charts are SVG drawn in the plugin.** The host has no chart library, and a screen may not bring one.

## Constraints

- **[2026-10-16] A Cost Management query covers at most a year**; history is twelve months.
- **[2026-10-16] A month is settled five days after it ends**; until then it is fetched again on refresh, after that never.
- **[2026-10-16] `az` must be on the backend's PATH and signed in as the operator.** A backend run as a service account would not see the operator's billing accounts.
