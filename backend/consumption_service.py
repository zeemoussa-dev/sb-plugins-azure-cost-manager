"""Answering for a customer from local data. Nothing here calls Azure: the sync
is the only thing that does (`consumption_sync`)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from . import (brief, consumption_analysis, memory, data_transfer, drill, placement, export_reports, export_xlsx, finops, forecasting, growth, hygiene,
               marketplace,
               marketplace_whitespace, months, pricing, quota, renewals, solution_plays, solutions, tags, this_month,
               whitespace)
from .consumption_store import ConsumptionStore
from .customers import CustomerBook, short_name
from .pipeline import Pipeline, PipelineUnavailable, by_month

class BriefUnavailable(RuntimeError):
    """No model to write a brief with on this framework."""


# Cost Management bills every Marketplace offer under these service names.
MARKETPLACE_SERVICES = ("SaaS", "Azure Applications")

# The weekly job keeps data at most a week old; past this the page says it is stale.
STALE_AFTER = timedelta(days=8)
# Who an analysis or a workbook is for: the operator, or the customer it is about.
VIEWS = ("account", "customer")
# The customer list's trend line: the last half-year of closed months.
RECENT_MONTHS = 6
# Running out this many months before the term ends is worth a renewal conversation.
EARLY_EXHAUSTION_MONTHS = 3


def _status(burn: dict | None, synced_at: str | None, covered_by_parent: bool = False) -> str:
    if not synced_at:
        return "not-synced"
    if not burn:
        # An affiliate that signs no MACC of its own consumes its parent's (DGE's
        # affiliates, operator 2026-10-21): it has no MACC to set.
        return "parent-macc" if covered_by_parent else "no-macc"
    if burn["remaining"] <= 0:
        return "consumed"
    if burn["projected_shortfall"] > 0:
        return "behind"
    exhaustion, end_month = burn["projected_exhaustion"], burn["end"][:7]
    if exhaustion and len(months.span(exhaustion, end_month)) - 1 >= EARLY_EXHAUSTION_MONTHS:
        return "early"
    return "on-track"


class CustomerNotFound(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConsumptionService:
    def __init__(self, store: ConsumptionStore, book: CustomerBook,
                 today: Callable[[], date] = date.today, now: Callable[[], datetime] = _now,
                 pipeline: Pipeline | None = None, solution_notes=None, technology_notes=None,
                 llm=None, customer_context=None) -> None:
        self._store = store
        self._book = book
        self._llm = llm
        self._customer_context = customer_context
        self.memory = memory.CustomerMemory(store.customer_memory, store.save_customer_memory, today)
        self._solution_notes = solution_notes
        self._technology_notes = technology_notes
        self.prices = pricing.PriceBook(store.finops_state, store.save_finops_state, now)
        self._pipeline = pipeline
        self._today = today
        self._now = now

    def current_month(self) -> str:
        """The month still being billed."""
        return months.month_of(self._today())

    def current_day(self) -> str:
        return self._today().isoformat()

    def customer(self, customer_id: str) -> dict:
        return self._customer(customer_id)

    def _customer(self, customer_id: str) -> dict:
        customer = next((listed for listed in self._book.list() if listed["id"] == customer_id), None)
        if customer is None:
            raise CustomerNotFound(f"no customer {customer_id!r}")
        return customer

    def _group(self, customer: dict) -> list[dict]:
        """The customer and, for a parent, its affiliates: everything its MACC covers."""
        affiliates = [listed for listed in self._book.list() if listed.get("parent") == customer["id"]]
        return [customer] + affiliates

    def _merged(self, customer: dict, rolled_up: bool = True,
                only: set[str] | None = None) -> tuple[dict, str | None, dict[str, dict]]:
        """`only`: just these enrollments of the group -- the ones the report shows."""
        accounts = {account["name"]: account for member in (self._group(customer) if rolled_up else [customer])
                    for account in member["accounts"] if only is None or account["name"] in only}
        entries = {name: self._store.account(name) for name in accounts}
        labels = {name: f"{account['display_name']} ({name})" for name, account in accounts.items()}
        merged, currency = consumption_analysis.merge(entries, labels, self._not_eligible())
        return merged, currency, entries

    def _not_eligible(self) -> set[str]:
        return marketplace.not_eligible_keys(self._store.not_macc_eligible())

    def _period(self, first: str | None, last: str | None) -> tuple[str | None, str]:
        """The last twelve months unless asked otherwise; `first="start"` is everything
        synced, from the first month there is data for."""
        default_first, default_last = marketplace.default_period(self._today().strftime("%Y-%m"))
        if first == "start":
            return None, last or default_last
        return first or default_first, last or default_last

    def marketplace(self, customer_id: str, first: str | None = None, last: str | None = None) -> dict:
        """The customer's (a group's: with its affiliates') Marketplace solutions."""
        customer = self._customer(customer_id)
        accounts = {account["name"]: account for member in self._group(customer) for account in member["accounts"]}
        entries = {name: self._store.account(name) for name in accounts}
        labels = {name: f"{account['display_name']} ({name})" for name, account in accounts.items()}
        first, last = self._period(first, last)
        return {"customer": {"id": customer["id"], "name": customer["name"]},
                **marketplace.customer_report(entries, labels, self._not_eligible(), first, last)}

    def marketplace_across(self, first: str | None = None, last: str | None = None) -> dict:
        """Every partner solution across every customer, each enrollment counted once."""
        first, last = self._period(first, last)
        everyone = self._book.list()
        # Affiliates before parents, so an affiliate's enrollment is credited to the affiliate.
        ordered = sorted(everyone, key=lambda customer: 0 if customer.get("parent") else 1)
        customers = [(customer, {account["name"]: self._store.account(account["name"])
                                 for account in customer["accounts"]}) for customer in ordered]
        in_customers = {account["name"] for customer in everyone for account in customer["accounts"]}
        profiles = marketplace.profile_groups(self._store.profile_accounts(in_customers))
        return marketplace.across_customers(customers + profiles, self._not_eligible(), first, last)

    def marketplace_whitespace(self, first: str | None = None, last: str | None = None) -> dict:
        """Marketplace bought from publishers other than Core42, by category and customer."""
        return marketplace_whitespace.analyse(self.marketplace_across(first, last))

    def not_macc_eligible(self) -> list[dict]:
        return self._store.not_macc_eligible()

    def set_macc_eligible(self, publisher: str, offer: str, eligible: bool) -> list[dict]:
        """Marks one offer as counting toward MACCs or not, for every customer."""
        if not publisher or not offer:
            raise ValueError("an offer is named by its publisher and its offer")
        current = [item for item in self._store.not_macc_eligible()
                   if (item["publisher"], item["offer"]) != (publisher, offer)]
        if not eligible:
            current.append({"publisher": publisher, "offer": offer})
        self._store.save_not_macc_eligible(current)
        return current

    # -- moving to another machine ----------------------------------------------

    def export_data(self) -> tuple[str, bytes]:
        """Every data file, zipped, for another machine (operator, 2026-10-23)."""
        archive = data_transfer.build(self._store.read_files(), self._now())
        return f"Azure Customer 360 data - {self._today().isoformat()}.zip", archive

    def import_data(self, content: bytes) -> dict:
        """Replaces this machine's data with an export's; says what came in."""
        from .consumption_store import CONSUMPTION_CACHE_FILE, CUSTOMERS_FILE, DATA_FILES
        files = data_transfer.read(content, DATA_FILES)
        self._store.replace_files(files)
        return data_transfer.summary(files, CUSTOMERS_FILE, CONSUMPTION_CACHE_FILE)

    # -- baseline and quota ------------------------------------------------------

    def quota_settings(self) -> dict:
        return quota.settings(self._store.quota_state(), months.month_of(self._today()))

    def save_quota_settings(self, changes: dict) -> dict:
        self._store.save_quota_state({**self._store.quota_state(), **quota.validated(changes)})
        return self.quota_settings()

    def _quota_of(self, customer: dict, measure: dict | None, chosen: dict) -> dict:
        """One customer (a group, with its affiliates) against the baseline."""
        current_month = months.month_of(self._today())
        merged, currency, _ = self._merged(customer)
        trend = consumption_analysis.monthly_totals(merged, current_month, measure)
        pipeline = self.pipeline(customer["id"])
        automatic = forecasting.automatic(trend, self._today(), pipeline["by_month"])
        found = quota.analyse(trend, (automatic or {}).get("series"), chosen, current_month)
        return {**found, "currency": (currency or "").strip() or None,
                "pipeline": quota.pipeline_against_actual(pipeline["opportunities"], found, current_month),
                "pipeline_available": pipeline["available"]}

    def quota_customer(self, customer_id: str, measure: dict | None = None) -> dict:
        """A customer's fiscal year above its baseline (operator, 2026-10-22)."""
        customer = self._customer(customer_id)
        chosen = self.quota_settings()
        return {"customer": {"id": customer["id"], "name": customer["name"]}, "settings": chosen,
                "measure": measure, **self._quota_of(customer, measure, chosen)}

    def quota_across(self, measure: dict | None = None) -> dict:
        """Every top-level customer above its baseline, and the seller's quota
        attainment: to date, projected, and projected with the pipeline."""
        chosen = self.quota_settings()
        rows = []
        for customer in self._book.list():
            if customer.get("parent"):
                continue
            found = self._quota_of(customer, measure, chosen)
            rows.append({"id": customer["id"], "name": customer["name"], "affiliates": len(customer.get("affiliates") or []),
                         **{key: found[key] for key in ("currency", "baseline", "baseline_covered", "above_to_date",
                                                        "above_projected", "above_with_pipeline")},
                         "pipeline": {key: found["pipeline"][key] for key in
                                      ("planned_to_date", "achieved_to_date", "gap", "behind")},
                         "missed": [item for item in found["pipeline"]["opportunities"]] if found["pipeline"]["behind"]
                         else []})
        rows.sort(key=lambda row: -row["above_projected"])
        totals = {key: round(sum(row[key] for row in rows), 2)
                  for key in ("above_to_date", "above_projected", "above_with_pipeline")}
        target = chosen.get("quota")

        def share(amount: float) -> float | None:
            return round(amount / target * 100, 1) if target else None
        return {"settings": chosen, "measure": measure, "customers": rows, **totals,
                "attained_pct": share(totals["above_to_date"]), "projected_pct": share(totals["above_projected"]),
                "with_pipeline_pct": share(totals["above_with_pipeline"]),
                "gap_to_quota": round(target - totals["above_projected"], 2) if target else None}

    # -- solutions: what each subscription is used for --------------------------

    def solution_catalog(self) -> dict:
        """The patterns from the vault's Solution notes, or the shipped ones when it has none."""
        if self._solution_notes is None:
            return {"patterns": solutions.patterns(None), "source": "shipped", "notes": []}
        return self._solution_notes.catalog()

    def _patterns(self) -> list[dict]:
        return self.solution_catalog()["patterns"]

    def _solutions_view(self, members: list[dict], catalog: list[dict]) -> dict:
        entries = {account["name"]: self._store.account(account["name"])
                   for member in members for account in member["accounts"]}
        return solutions.customer_view(entries, catalog)

    def solutions_of(self, customer_id: str) -> dict:
        """Each of the customer's subscriptions (a group's: with its affiliates'), the
        solution it looks like, and what to pitch (operator, 2026-10-23)."""
        customer = self._customer(customer_id)
        catalog = self._patterns()
        return {"customer": {"id": customer["id"], "name": customer["name"]},
                **self._solutions_view(self._group(customer), catalog)}

    def solutions_across(self) -> dict:
        everyone = self._book.list()
        catalog = self._patterns()
        views = [(customer, self._solutions_view(
            [customer] + [listed for listed in everyone if listed.get("parent") == customer["id"]], catalog))
            for customer in everyone if not customer.get("parent")]
        return solutions.across(views)

    def brief_facts(self, customer_id: str) -> dict:
        """Everything the reports know about one customer, as the brief and the seller's other
        Compass features are handed it."""
        customer = self._customer(customer_id)
        analysis = self._analysis(customer_id)
        try:
            quota_found = self.quota_customer(customer_id)
        except ValueError:
            quota_found = None
        sizing = {pattern["name"]: [pattern["sizing"]["totals"][size] for size in ("small", "medium", "large")]
                  for pattern in self._patterns() if pattern.get("sizing")}
        vault = self._customer_context.about(customer.get("entity_customer")) if self._customer_context else {}
        return brief.facts(customer, analysis, quota_found, self.solutions_of(customer_id), sizing, vault,
                           self.memory.handed(customer_id))

    def customer_brief(self, customer_id: str, write: bool = False) -> dict:
        """The customer's brief before a meeting (operator, 2026-10-23), written by Compass
        over the facts the reports computed. `write`: write it now, even when the facts
        have not changed; otherwise the kept one is returned, `stale` when they have."""
        found = self.brief_facts(customer_id)
        stamp = brief.fingerprint(found)
        kept = self._store.brief(customer_id)
        available = bool(self._llm and self._llm.available())
        if not write:
            return {**(kept or {}), "kept": bool(kept), "stale": bool(kept) and kept.get("fingerprint") != stamp,
                    "available": available, "facts": found}
        if self._llm is None:
            raise BriefUnavailable("The customer brief needs a framework that offers Compass to plugins "
                                   "(api.llm, ADR-063): update Second Brain")
        written = {"markdown": self._llm.complete(brief.messages(found), timeout=180.0),
                   "generated_at": self._now().isoformat(), "fingerprint": stamp}
        self._store.save_brief(customer_id, written)
        return {**written, "kept": True, "stale": False, "available": available, "facts": found}

    def _unplaced(self, customer_id: str | None) -> list[dict]:
        """What Compass would be shown: every subscription the rules did not place, the
        largest first -- one customer's, or every customer's."""
        if customer_id:
            view = self.solutions_of(customer_id)
            rows = [(view["customer"], row) for row in view["subscriptions"] if not row["solutions"]]
        else:
            rows = [({"id": row["customer_id"], "name": row["customer"]}, row)
                    for row in self.solutions_across()["unclassified"]]
        found = [placement.subject(customer, row) for customer, row in rows]
        return sorted(found, key=lambda item: -item["monthly"])

    def placements(self, customer_id: str | None = None) -> dict:
        """Compass's placements of the unplaced subscriptions it has been asked about and
        whose services have not changed since, and the new solutions it proposed."""
        subjects = {item["key"]: item for item in self._unplaced(customer_id)}
        kept = self._store.placements()
        current = {key: {**kept[key]["suggestion"], "customer": item["customer"], "subscription": item["subscription"],
                         "monthly": item["monthly"]} for key, item in subjects.items()
                   if key in kept and kept[key].get("fingerprint") == placement.fingerprint(item)}
        return {"available": bool(self._llm and self._llm.available()),
                "suggestions": current, "unplaced": len(subjects),
                "pending": [key for key in subjects if key not in current],
                "proposals": placement.proposals(current, subjects)}

    def place(self, customer_id: str | None = None, limit: int = 24) -> dict:
        """Asks Compass about the largest unplaced subscriptions not asked about yet
        (operator, 2026-10-23: the second part of LLM enablement)."""
        if self._llm is None:
            raise BriefUnavailable("Placing subscriptions needs a framework that offers Compass to plugins "
                                   "(api.llm, ADR-063): update Second Brain")
        state = self.placements(customer_id)
        subjects = {item["key"]: item for item in self._unplaced(customer_id)}
        asking = [subjects[key] for key in state["pending"]][:max(1, min(limit, 60))]
        catalog = self._patterns()
        for start in range(0, len(asking), placement.BATCH):
            batch = asking[start:start + placement.BATCH]
            found = placement.parse(self._llm.complete(placement.messages(batch, catalog), timeout=180.0), batch, catalog)
            stamp = self._now().isoformat()
            self._store.save_placements({key: {"fingerprint": placement.fingerprint(subjects[key]), "suggestion": answer,
                                               "asked_at": stamp} for key, answer in found.items()})
        return self.placements(customer_id)

    def proposal_note(self, name: str) -> dict:
        """A proposed solution as a Solution note to paste into the vault."""
        found = next((item for item in self.placements()["proposals"] if item["name"].lower() == name.lower()), None)
        if not found:
            raise ValueError(f"no proposed solution named {name!r}")
        return {"name": found["name"], "file": f"Work/Solutions/{found['name']}.md",
                "markdown": placement.solution_note(found, self._today().isoformat())}

    def guide(self) -> dict:
        """The Solutions Guide without choosing a customer (operator, 2026-10-23: "I don't
        have a way to navigate to it unless I am inside a customer"): the playbooks, the
        solutions with who runs them, and every service billed or written up, with the
        customers using it."""
        catalog = self._patterns()
        across = self.solutions_across()
        running = {item["id"]: item for item in across["by_solution"]}
        notes = self._technology_notes
        plays = self.solution_play_mapping()
        everyone = self._book.list()
        current_month = months.month_of(self._today())
        used: dict[str, dict] = {}
        # What "SaaS" and "Azure Applications" are across every customer: the Marketplace
        # products behind them (operator, 2026-10-23), each with the customers buying it.
        products: dict[tuple, dict] = {}
        for customer in everyone:
            if customer.get("parent"):
                continue
            members = [customer] + [listed for listed in everyone if listed.get("parent") == customer["id"]]
            entries = {account["name"]: self._store.account(account["name"])
                       for member in members for account in member["accounts"]}
            merged, _ = consumption_analysis.merge(entries, None, set())
            recent = [month for month in sorted(merged) if month < current_month][-3:]
            for product in self._marketplace_behind(entries, recent):
                key = (product["publisher"], product["offer"], product["plan"])
                row = products.setdefault(key, {"publisher": key[0], "offer": key[1], "plan": key[2],
                                                "recurring": product.get("recurring"), "customers": [], "monthly": 0.0})
                row["customers"].append({"id": customer["id"], "name": customer["name"], "monthly": product["monthly"]})
                row["monthly"] = round(row["monthly"] + product["monthly"], 2)
            totals: dict[str, float] = {}
            for month in recent:
                for service, cost in (merged[month]["actual"].get("service") or {}).items():
                    totals[service] = totals.get(service, 0.0) + cost
            for service, cost in totals.items():
                monthly = round(cost / max(1, len(recent)), 2)
                if monthly < 1:
                    continue
                row = used.setdefault(service, {"customers": [], "monthly": 0.0})
                row["customers"].append({"id": customer["id"], "name": customer["name"], "monthly": monthly})
                row["monthly"] = round(row["monthly"] + monthly, 2)
        signals = {pattern["id"]: {signal for group in pattern["requires"] for signal in group} | set(pattern["supports"])
                   for pattern in catalog}
        services = []
        noted = set()
        for service, row in used.items():
            stem = notes.note_for(service) if notes else None
            noted.add(stem)
            services.append({"name": service, "note": stem, "play": solution_plays.play_of(service, plays),
                             **({"marketplace": sorted(products.values(), key=lambda item: -item["monthly"])}
                                if service in MARKETPLACE_SERVICES else {}),
                             "customers": sorted(row["customers"], key=lambda item: -item["monthly"]),
                             "monthly": row["monthly"],
                             "solutions": [{"id": pattern["id"], "name": pattern["name"], "note": pattern.get("note")}
                                           for pattern in catalog if f"service:{service}" in signals[pattern["id"]]]})
        for note in (notes.notes() if notes else []):
            if note["stem"] not in noted:
                services.append({"name": note["title"], "note": note["stem"], "play": None, "customers": [],
                                 "monthly": 0.0, "solutions": [], "category": note.get("category")})
        return {
            "window": across["window"],
            "playbooks": self._solution_notes.playbooks() if self._solution_notes else [],
            "solutions": [{"id": pattern["id"], "name": pattern["name"], "play": pattern["play"],
                           "note": pattern.get("note"), "description": pattern.get("description"),
                           "sizing": pattern.get("sizing"), "architecture": pattern.get("architecture"),
                           "customers": (running.get(pattern["id"]) or {}).get("customers") or [],
                           "monthly": (running.get(pattern["id"]) or {}).get("monthly") or 0.0} for pattern in catalog],
            "services": sorted(services, key=lambda item: (-item["monthly"], item["name"].lower())),
        }

    def export_report(self, report: str, measure: dict | None = None) -> tuple[str, bytes]:
        """`(file name, .xlsx bytes)` for one of the cross-customer reports, on the
        plugin's workbook template (operator, 2026-10-21)."""
        today = self._today()
        builders = {
            "growth": ("Growth and churn", lambda: export_reports.build_growth(self.growth_across(), today)),
            "whitespace": ("Service whitespace", lambda: export_reports.build_whitespace(self.whitespace_across(), today)),
            "marketplace-whitespace": ("Marketplace whitespace", lambda: export_reports.build_marketplace_whitespace(
                self.marketplace_whitespace(), today)),
            "hygiene": ("Subscription and tag hygiene", lambda: export_reports.build_hygiene(self.hygiene_across(), today)),
            "renewals": ("Marketplace renewals", lambda: export_reports.build_renewals(self.renewals(), today)),
            "quota": ("Baseline and quota", lambda: export_reports.build_quota(self.quota_across(measure), today)),
            "solutions": ("Solutions", lambda: export_reports.build_solutions(self.solutions_across(), today)),
        }
        if report not in builders:
            raise ValueError(f"report is one of {', '.join(builders)}")
        title, build = builders[report]
        return f"Azure {title} - all customers - {today.isoformat()}.xlsx", build()

    def export_marketplace(self, first: str | None = None, last: str | None = None) -> tuple[str, bytes]:
        report = self.marketplace_across(first, last)
        workbook = export_xlsx.build_marketplace(report, self._today())
        return f"Azure Marketplace - all customers - {self._today().isoformat()}.xlsx", workbook

    def _allocations(self, parent: dict, affiliates: list[dict]) -> dict | None:
        """How the parent's MACC is carved up: each affiliate against its own MACC,
        and the unallocated rest against the parent's own enrollments."""
        commitment = parent.get("commitment")
        if not affiliates:
            return None
        current_month = self._today().strftime("%Y-%m")

        def burn_of(member: dict, signed: dict | None) -> tuple[dict | None, float]:
            merged, _, _ = self._merged(member, rolled_up=False)
            measure = consumption_analysis.commitment_measure(signed or commitment or {})
            trend = consumption_analysis.monthly_totals(merged, current_month, measure)
            burn = consumption_analysis.burn_down(signed, trend, self._today()) if signed else None
            within = trend
            if commitment:
                first, last = commitment["start"][:7], commitment["end"][:7]
                within = [month for month in trend if first <= month["month"] <= last]
            return burn, round(sum(month["actual"] for month in within), 2)

        rows = []
        for affiliate in affiliates:
            burn, against_parent = burn_of(affiliate, affiliate.get("commitment"))
            rows.append({"id": affiliate["id"], "name": affiliate["name"], "commitment": affiliate.get("commitment"),
                         "burn": burn, "consumed_against_parent": against_parent})
        allocated = sum((row["commitment"] or {}).get("amount", 0.0) for row in rows)
        _, own_consumed = burn_of(parent, None)
        amount = (commitment or {}).get("amount")
        unallocated = None if amount is None else amount - allocated
        return {
            "parent_amount": amount,
            "allocated": round(allocated, 2),
            "unallocated": None if unallocated is None else round(unallocated, 2),
            "over_allocated": bool(amount is not None and allocated > amount),
            "own": {"consumed": own_consumed,
                    "remaining": None if unallocated is None else round(unallocated - own_consumed, 2)},
            "affiliates": rows,
            "consumed_total": round(own_consumed + sum(row["consumed_against_parent"] for row in rows), 2),
        }

    def pipeline(self, customer_id: str) -> dict:
        """The customer's opportunities and what they add by month, or why there are none."""
        customer = self._customer(customer_id)
        if self._pipeline is None:
            return {"available": False, "reason": "no pipeline source", "opportunities": [], "by_month": {}}
        try:
            opportunities = self._pipeline.opportunities(customer)
        except PipelineUnavailable as exc:
            return {"available": False, "reason": str(exc), "opportunities": [], "by_month": {}}
        reason = None if customer.get("entity_customer") else \
            "Link this customer to its Customer note to see and plan its opportunities."
        return {"available": True, "reason": reason, "linked": bool(customer.get("entity_customer")),
                "opportunities": opportunities, "by_month": by_month(opportunities)}

    def _group_info(self, customer: dict, members: list[dict]) -> dict:
        parent = None
        if customer.get("parent"):
            record = next((listed for listed in self._book.list() if listed["id"] == customer["parent"]), None)
            if record:
                parent = {"id": record["id"], "name": record["name"],
                          "amount": (record.get("commitment") or {}).get("amount"),
                          "currency": (record.get("commitment") or {}).get("currency"),
                          "entity_customer": record.get("entity_customer"),
                          # Whether this customer's consumption counts toward the parent's MACC.
                          "rolls_up": bool(record.get("commitment"))
                          and consumption_analysis.affiliates_roll_up(record.get("commitment"))}
        return {"parent": parent,
                "affiliates": [{"id": member["id"], "name": member["name"]} for member in members[1:]],
                "accounts": [{**account, "member": member["name"], "member_id": member["id"],
                              "short_name": short_name(account.get("display_name") or account["name"])}
                             for member in members for account in member["accounts"]]}

    def analysis(self, customer_id: str, measure: dict | None = None, view: str = "account",
                 accounts: list[str] | None = None) -> dict:
        """`accounts`: show only these of the group's enrollments (operator, 2026-10-21:
        "select some of them to display their data"); None or empty shows them all."""
        if view not in VIEWS:
            raise ValueError("view is account or customer")
        found = self._analysis(customer_id, measure, accounts)
        if view == "customer":
            # Left out on the server, so nothing the Customer view hides reaches the browser.
            return {**found, "scenarios": None, "customer": {**found["customer"], "scenario": None},
                    "customer_view": True}
        return found

    def _plays_by_month(self, merged: dict) -> list[dict]:
        """Actual cost by solution play per month (Cost Management's figures, so
        Marketplace in and credits not subtracted, as in Breakdown)."""
        plays = self.solution_play_mapping()
        return [{"month": month, "by_play": solution_plays.split(
                    merged[month]["actual"]["service"], merged[month].get("meters"), plays,
                    (merged[month].get("measured") or {}).get("marketplace"))}
                for month in sorted(merged)]

    def _analysis(self, customer_id: str, measure: dict | None = None, accounts: list[str] | None = None) -> dict:
        customer = self._customer(customer_id)
        members = self._group(customer)
        in_group = [account["name"] for member in members for account in member["accounts"]]
        only = {name for name in accounts or [] if name in in_group} or None
        if accounts and not only:
            raise ValueError("none of those enrollments belong to this customer")
        merged, currency, entries = self._merged(customer, only=only)
        # Affiliates that signed their own: the group is shown, the parent's own burns its MACC.
        own_burn = len(members) > 1 and not consumption_analysis.affiliates_roll_up(customer.get("commitment"))
        # The MACC consumed is the commitment's, whichever enrollments are shown: a
        # selection must never make a MACC look less consumed than it is.
        burn_merged = (self._merged(customer, rolled_up=False)[0] if own_burn
                       else self._merged(customer)[0] if only else None)
        synced = [account["synced_at"] for member in members for account in member["accounts"]]
        synced_at = min(synced) if synced and all(synced) else None
        pipeline = self.pipeline(customer_id)
        as_of = consumption_analysis.report_date(self._today(), (measure or {}).get("billing_day"))
        return {
            "as_of": as_of.isoformat(),
            "shown_accounts": sorted(only) if only else in_group,
            "solution_plays": self._plays_by_month(merged),
            "customer": customer,
            "group": self._group_info(customer, members),
            # Carving affiliates out of the parent's MACC applies only when they roll up into it.
            "allocations": None if own_burn else self._allocations(customer, members[1:]),
            "synced_at": synced_at,
            "stale": not synced_at or self._now() - datetime.fromisoformat(synced_at) > STALE_AFTER,
            "errors": {account: entry.get("errors") for account, entry in entries.items() if entry.get("errors")},
            "pipeline": pipeline,
            **consumption_analysis.analyse(merged, currency, customer.get("commitment"),
                                           consumption_analysis.merge_forecasts(entries), as_of,
                                           measure=measure, scenario=customer.get("scenario"),
                                           pipeline=pipeline["by_month"],
                                           burn_merged=burn_merged),
        }

    def _finops_of(self, customer: dict) -> dict:
        members = self._group(customer)
        merged, currency, entries = self._merged(customer)
        current_month = months.month_of(self._today())
        commitment = customer.get("commitment")
        trend = consumption_analysis.monthly_totals(merged, current_month,
                                                    consumption_analysis.commitment_measure(commitment or {}))
        outlook = consumption_analysis.forecast(trend, consumption_analysis.merge_forecasts(entries), self._today())
        this_month = next((row["cost"] for row in outlook["months"] if row["month"] == current_month), None)
        return {"customer": {"id": customer["id"], "name": customer["name"], "parent": customer.get("parent"),
                             "affiliates": [member["id"] for member in members[1:]],
                             # Where "Create opportunity" files a finding: the linked Customer note.
                             "entity_customer": customer.get("entity_customer")},
                # The Consumption API pads the currency code ("USD  ").
                "currency": (currency or "").strip() or None,
                **finops.analyse(entries, merged, trend, commitment, customer.get("budget_monthly"), this_month,
                                 self._today(), self.prices.discounts()),
                "pricing_region": self.prices.region()}

    def finops(self, customer_id: str) -> dict:
        """The FinOps findings for one customer (a group: with its affiliates). The
        Customer view shows the same findings: nothing here is internal."""
        return self._finops_of(self._customer(customer_id))

    def finops_across(self) -> list[dict]:
        """Every top-level customer's FinOps at a glance, the largest steady
        on-demand spend first -- where the savings conversations are."""
        everyone = self._book.list()
        rows = []
        for customer in everyone:
            if customer.get("parent"):
                continue
            found = self._finops_of(customer)
            latest = found["coverage"]["latest"]
            rows.append({"id": customer["id"], "name": customer["name"], "affiliates": found["customer"]["affiliates"],
                         "currency": found["currency"], "has_meters": found["has_meters"],
                         "coverage_pct": latest["coverage_pct"] if latest else None,
                         "on_demand": latest["on_demand"] if latest else None,
                         "coverage_month": latest["month"] if latest else None,
                         "candidates": len(found["candidates"]), "candidates_monthly": found["candidates_monthly"],
                         "top_candidate": found["candidates"][0]["meter"] if found["candidates"] else None,
                         "savings_monthly": found["savings_monthly"],
                         "budget": found["budget"]})
        return sorted(rows, key=lambda row: (-row["candidates_monthly"], row["name"].lower()))

    def _tags_of(self, customer: dict) -> dict:
        merged, currency, entries = self._merged(customer)
        totals = {month: sum(((data.get("actual") or {}).get("service") or {}).values())
                  for month, data in merged.items()}
        return {"customer": {"id": customer["id"], "name": customer["name"]},
                "currency": (currency or "").strip() or None,
                "synced": any((entry.get("tags") or {}).get("keys_fetched_at") for entry in entries.values()),
                **tags.report(entries, totals, months.month_of(self._today()))}

    def tags(self, customer_id: str) -> dict:
        """A customer's cost by business tag -- Environment, Project, Application,
        Business unit, Owner, Cost centre -- with coverage and the spellings behind
        each. Nothing here is internal: the Customer view shows it all."""
        return self._tags_of(self._customer(customer_id))

    def tags_across(self) -> list[dict]:
        """Every top-level customer's tag coverage, per dimension, last closed month."""
        rows = []
        for customer in self._book.list():
            if customer.get("parent"):
                continue
            found = self._tags_of(customer)
            rows.append({"id": customer["id"], "name": customer["name"], "synced": found["synced"],
                         "tag_keys": found["tag_keys"],
                         "coverage": {item["dimension"]: item["coverage_pct"] for item in found["dimensions"]},
                         "spellings": {item["dimension"]: len(item["all_spellings"]) for item in found["dimensions"]}})
        return sorted(rows, key=lambda row: row["name"].lower())

    def unassigned(self, visible: list[dict]) -> list[dict]:
        """Billing accounts this sign-in sees that belong to no customer, grouped as
        Settings suggests (a renewal, or linked under one parent), each group with
        what it consumed -- from the light sync of billing profiles, so no Azure call.
        The biggest first: those are the customers worth adding."""
        assigned = {account["name"] for customer in self._book.list() for account in customer["accounts"]}
        current = months.month_of(self._today())
        last_closed = months.shift(current, -1)
        year = set(months.span(months.shift(current, -12), last_closed))
        groups: dict[str, dict] = {}
        for account in visible:
            if account["name"] in assigned:
                continue
            entry = self._store.account(account["name"])
            by_month: dict[str, float] = {}
            for month, data in (entry.get("months") or {}).items():
                balance = data.get("balance") or {}
                if balance and not balance.get("missing"):
                    by_month[month] = balance.get("usage", 0.0) + balance.get("marketplace", 0.0) - balance.get("credits", 0.0)
                elif data.get("actual"):
                    by_month[month] = sum(((data.get("actual") or {}).get("service") or {}).values())
            group = groups.setdefault(account.get("group_key") or account["name"], {
                "key": account.get("group_key") or account["name"], "accounts": [], "last_month": 0.0,
                "last_twelve_months": 0.0, "synced": False})
            group["accounts"].append({"name": account["name"], "display_name": account.get("display_name") or account["name"],
                                      "agreement_type": account.get("agreement_type"),
                                      "term_start": account.get("term_start"), "term_end": account.get("term_end"),
                                      "last_month": round(by_month.get(last_closed, 0.0), 2),
                                      "last_twelve_months": round(sum(cost for month, cost in by_month.items()
                                                                      if month in year), 2)})
            group["last_month"] += by_month.get(last_closed, 0.0)
            group["last_twelve_months"] += sum(cost for month, cost in by_month.items() if month in year)
            group["synced"] = group["synced"] or bool(by_month)
        listed = []
        for group in groups.values():
            names = [account["display_name"] for account in group["accounts"]]
            listed.append({**group, "name": min(names, key=len), "last_month_label": last_closed,
                           "last_month": round(group["last_month"], 2),
                           "last_twelve_months": round(group["last_twelve_months"], 2),
                           "accounts": sorted(group["accounts"], key=lambda account: account["display_name"].lower())})
        return sorted(listed, key=lambda group: (-group["last_twelve_months"], group["name"].lower()))

    def own_monthly(self, customer: str | dict, measure: dict) -> tuple[list[dict], str | None, dict | None]:
        """`(monthly totals, currency, commitment)` of a customer's OWN enrollments --
        a parent without its affiliates' -- measured with `measure`. `customer` is an
        id, or the customer record already in hand (which saves listing customers)."""
        customer = self._customer(customer) if isinstance(customer, str) else customer
        merged, currency, _ = self._merged(customer, rolled_up=False)
        trend = consumption_analysis.monthly_totals(merged, months.month_of(self._today()), measure)
        return trend, (currency or "").strip() or None, customer.get("commitment")

    def this_month(self, customer_id: str) -> dict:
        """This month so far for a customer (a group: with its affiliates), from the
        on-demand daily refresh: pace against last month, and what is new or moving."""
        customer = self._customer(customer_id)
        merged, currency, entries = self._merged(customer)
        return {"customer": {"id": customer["id"], "name": customer["name"],
                             "entity_customer": customer.get("entity_customer")},
                "currency": (currency or "").strip() or None,
                **this_month.analyse(entries, merged, self._today())}

    def finops_digest(self, top: int = 5) -> dict:
        """The week's FinOps in a few lines, for a Hermes job to send: who is over
        budget, and where the largest savings are. Text, not a page."""
        rows = self.finops_across()
        over = [row for row in rows if (row["budget"] or {}).get("status") in ("over", "forecast-over")]
        priced = sorted((row for row in rows if (row["savings_monthly"] or {}).get("ri_3y")),
                        key=lambda row: -row["savings_monthly"]["ri_3y"])

        def money(value: float) -> str:
            if value >= 1_000_000:
                return f"${value / 1_000_000:.2f}M"
            return f"${value / 1_000:.0f}k" if value >= 1_000 else f"${value:,.0f}"

        lines = [f"Azure FinOps – week of {self._today().isoformat()}"]
        if priced:
            total = sum(row["savings_monthly"]["ri_3y"] for row in priced)
            lines += ["", f"Estimated savings on steady on-demand spend: {money(total)} a month on 3-year reservations."]
            lines += [f"• {row['name']}: {money(row['savings_monthly']['ri_3y'])}/mo "
                      f"({row['candidates']} meters, largest {row['top_candidate']})" for row in priced[:top]]
        if over:
            lines += ["", "Over budget:"]
            lines += [f"• {row['name']}: {money(row['budget']['last_month_actual'] or 0)} in {row['budget']['last_month']} "
                      f"against {money(row['budget']['amount'])}"
                      + (" (forecast over this month)" if row['budget']['status'] == "forecast-over" else "")
                      for row in over[:top]]
        # New this month: only where "Refresh this month" has run -- it is on demand
        # (operator, 2026-10-18), so the digest says how fresh each customer's view is.
        news = []
        for customer in self._book.list():
            if customer.get("parent"):
                continue
            found = self.this_month(customer["id"])
            if found.get("has_data") and found["new_workloads"]:
                news.append((customer["name"], found))
        if news:
            lines += ["", "New this month (possible opportunities):"]
            for name, found in sorted(news, key=lambda item: -sum(w["this_month"] for w in item[1]["new_workloads"])):
                workloads = ", ".join(f"{w['kind_label'].lower()} {w['name']} ({money(w['this_month'])})"
                                      for w in found["new_workloads"][:top])
                more = len(found["new_workloads"]) - top
                lines.append(f"• {name}: {workloads}" + (f" and {more} more" if more > 0 else "")
                             + f" -- data to {found['through'] or 'n/a'}")
        if len(lines) == 1:
            lines += ["", "Nothing to flag this week."]
        return {"text": "\n".join(lines), "customers": len(rows), "over_budget": len(over), "with_savings": len(priced)}

    def meters_to_price(self) -> list[str]:
        """Every VM and GPU meter that is a steady candidate for some customer."""
        return sorted({candidate["meter"] for customer in self._book.list() if not customer.get("parent")
                       for candidate in self._finops_of(customer)["candidates"]
                       if candidate["family"] in finops.PRICED_FAMILIES})

    def refresh_prices(self, retail: pricing.RetailPrices | None = None) -> dict:
        """Prices every candidate meter not priced this month (Retail Prices API,
        no sign-in). Run by the sync after customers, or on demand."""
        return self.prices.refresh(retail or pricing.RetailPrices(), self.meters_to_price())

    def set_pricing_region(self, region: str) -> dict:
        """Where steady candidates are priced; existing prices for other regions stay."""
        region = region.strip().lower()
        if not re.fullmatch(r"[a-z0-9]{3,30}", region):
            raise ValueError("a region is an Azure region name, e.g. uaenorth")
        state = self._store.finops_state()
        state["pricing_region"] = region
        self._store.save_finops_state(state)
        return {"pricing_region": region}

    def growth_across(self) -> list[dict]:
        """Every customer's growth and churn signals (operator, 2026-10-21), a group
        with its affiliates as its report shows it, the largest last month first."""
        everyone = self._book.list()
        current_month = months.month_of(self._today())
        cached: dict[str, dict] = {}
        not_eligible = self._not_eligible()
        plays = self.solution_play_mapping()
        rows = []
        for customer in everyone:
            members = [customer] + [listed for listed in everyone if listed.get("parent") == customer["id"]]
            names = [account["name"] for member in members for account in member["accounts"]]
            for name in names:
                if name not in cached:
                    cached[name] = self._store.account(name)
            merged, currency = consumption_analysis.merge({name: cached[name] for name in names}, None, not_eligible)
            trend = consumption_analysis.monthly_totals(merged, current_month)
            rows.append({"id": customer["id"], "name": customer["name"], "parent": customer.get("parent"),
                         "affiliates": len(members) - 1,
                         "currency": (currency or "").strip() or None,
                         **growth.analyse(trend, merged, plays)})
        return sorted(rows, key=lambda row: -(row.get("last_total") or 0))

    def hygiene_across(self) -> list[dict]:
        """Every top-level customer's subscription estate and tag coverage
        (operator, 2026-10-21), the most subscriptions first."""
        everyone = self._book.list()
        current_month = months.month_of(self._today())
        coverage = {row["id"]: row for row in self.tags_across()}
        rows = []
        for customer in everyone:
            if customer.get("parent"):
                continue
            members = [customer] + [listed for listed in everyone if listed.get("parent") == customer["id"]]
            merged, _ = consumption_analysis.merge(
                {account["name"]: self._store.account(account["name"]) for member in members
                 for account in member["accounts"]}, None, set())
            found = hygiene.analyse(merged, current_month)
            if not found.get("last_month"):
                continue
            tagged = coverage.get(customer["id"]) or {}
            rows.append({"id": customer["id"], "name": customer["name"], **found,
                         "tags_synced": bool(tagged.get("synced")), "tag_coverage": tagged.get("coverage") or {}})
        return sorted(rows, key=lambda row: -row["subscriptions"])

    def renewals(self) -> list[dict]:
        """Every recurring Marketplace purchase's next expected charge, customers'
        and other billing profiles' alike (operator, 2026-10-21)."""
        everyone = self._book.list()
        buyers = [(customer["name"], {account["name"]: self._store.account(account["name"])
                                      for account in customer["accounts"]}) for customer in everyone]
        in_customers = {account["name"] for customer in everyone for account in customer["accounts"]}
        buyers += [(profile["name"], entries)
                   for profile, entries in marketplace.profile_groups(self._store.profile_accounts(in_customers))]
        return renewals.calendar(buyers, months.month_of(self._today()))

    def whitespace_across(self) -> list[dict]:
        """Every top-level customer's service gaps against its peers (operator,
        2026-10-21), the customer with the most common services missing first."""
        everyone = self._book.list()
        current_month = months.month_of(self._today())
        tops = [customer for customer in everyone if not customer.get("parent")]
        usage = {}
        for customer in tops:
            members = [customer] + [listed for listed in everyone if listed.get("parent") == customer["id"]]
            merged, _ = consumption_analysis.merge(
                {account["name"]: self._store.account(account["name"]) for member in members
                 for account in member["accounts"]}, None, set())
            usage[customer["id"]] = whitespace.usage(merged, current_month)
        found = whitespace.analyse(usage, self.solution_play_mapping())
        rows = [{"id": customer["id"], "name": customer["name"],
                 "entity_customer": customer.get("entity_customer"),
                 "currency": ((customer.get("commitment") or {}).get("currency") or "USD").strip() or "USD",
                 **found[customer["id"]]} for customer in tops if found[customer["id"]]["uses"]]
        # The largest customers first: a gap at a big estate is the bigger conversation,
        # and a customer that uses nothing at $500 a month yet has no peers' pattern to miss.
        return sorted(rows, key=lambda row: -row["monthly"])

    def portfolio(self, only: str | None = None) -> list[dict]:
        """Every customer at a glance -- burn, last month, recent trend, status -- for
        the customer list (`only`: just that customer). A parent rolls up its
        affiliates, as its report does."""
        everyone = self._book.list()
        today = self._today()
        current_month = months.month_of(today)
        cached: dict[str, dict] = {}

        def entry(account: str) -> dict:
            if account not in cached:
                cached[account] = self._store.account(account)
            return cached[account]

        not_eligible = self._not_eligible()
        rows = []
        for customer in everyone:
            if only and customer["id"] != only:
                continue
            members = [customer] + [listed for listed in everyone if listed.get("parent") == customer["id"]]
            accounts = [account["name"] for member in members for account in member["accounts"]]
            merged, currency = consumption_analysis.merge({name: entry(name) for name in accounts},
                                                          None, not_eligible)
            commitment = customer.get("commitment")
            measure = consumption_analysis.commitment_measure(commitment or {})
            trend = consumption_analysis.monthly_totals(merged, current_month, measure)
            closed = [month for month in trend if not month["partial"]]
            burning = trend
            if len(members) > 1 and not consumption_analysis.affiliates_roll_up(commitment):
                own, _ = consumption_analysis.merge({account["name"]: entry(account["name"])
                                                     for account in customer["accounts"]}, None, not_eligible)
                burning = consumption_analysis.monthly_totals(own, current_month, measure)
            burn = consumption_analysis.burn_down(commitment, burning, today) if commitment else None
            # A group whose affiliates are mid-sync still has something to show: its
            # oldest synced enrollment dates it, and the rest are counted.
            synced = [account["synced_at"] for member in members for account in member["accounts"]
                      if account.get("synced_at")]
            synced_at = min(synced) if synced else None
            parent = next((listed for listed in everyone if listed["id"] == customer.get("parent")), None)
            covered = bool(parent and not commitment and parent.get("commitment")
                           and consumption_analysis.affiliates_roll_up(parent.get("commitment")))
            rows.append({
                "id": customer["id"],
                "name": customer["name"],
                "parent": customer.get("parent"),
                "covered_by": parent["name"] if covered else None,
                "affiliates": [member["id"] for member in members[1:]],
                "enrollments": len(accounts),
                # The Consumption API pads the currency code ("USD  ").
                "currency": ((commitment or {}).get("currency") or currency or "").strip() or None,
                "signed": (commitment or {}).get("amount"),
                "allocated": round(sum((member.get("commitment") or {}).get("amount", 0.0) for member in members[1:]), 2)
                if len(members) > 1 else None,
                "burn": None if not burn else {key: burn[key] for key in (
                    "consumed", "remaining", "consumed_pct", "elapsed_pct", "projected_at_end",
                    "projected_shortfall", "projected_exhaustion", "end")},
                "last_month": closed[-1] if closed else None,
                "recent": [{"month": month["month"], "actual": month["actual"]} for month in closed[-RECENT_MONTHS:]],
                "status": _status(burn, synced_at, covered),
                "synced_at": synced_at,
                "unsynced_enrollments": len(accounts) - len(synced),
                "stale": not synced_at or self._now() - datetime.fromisoformat(synced_at) > STALE_AFTER,
            })
        return rows

    # -- solution plays ----------------------------------------------------------

    def solution_play_mapping(self) -> dict[str, str]:
        return solution_plays.mapping(self._store.solution_play_overrides())

    def solution_plays_settings(self) -> dict:
        """Every service any synced customer was billed for, with its spend and play."""
        seen: dict[str, float] = {}
        for customer in self._book.list():
            for account in customer["accounts"]:
                for data in (self._store.account(account["name"]).get("months") or {}).values():
                    for service, cost in ((data.get("actual") or {}).get("service") or {}).items():
                        seen[service] = seen.get(service, 0.0) + cost
        return solution_plays.settings_view(self._store.solution_play_overrides(), seen)

    def set_solution_play(self, service: str, play: str | None) -> dict:
        """Maps one service to a play; None puts it back to the default."""
        if not service:
            raise ValueError("name the service")
        if play is not None and play not in solution_plays.PLAYS:
            raise ValueError(f"play must be one of {', '.join(solution_plays.PLAYS)}")
        overrides = self._store.solution_play_overrides()
        if play is None or play == solution_plays.DEFAULT_MAPPING.get(service):
            overrides.pop(service, None)
        else:
            overrides[service] = play
        self._store.save_solution_play_overrides(overrides)
        return self.solution_plays_settings()

    def export(self, customer_id: str, measure: dict | None = None, view: str = "account",
               accounts: list[str] | None = None) -> tuple[str, bytes]:
        """`(file name, .xlsx bytes)` for one customer. `view="customer"` is the workbook handed
        to the customer: everything but the forecast scenarios (operator, 2026-10-17)."""
        if view not in VIEWS:
            raise ValueError("view is account or customer")
        analysis = {**self.analysis(customer_id, measure, accounts=accounts), "finops": self.finops(customer_id),
                    "tags": self.tags(customer_id)}
        if view == "customer":
            analysis = {**analysis, "customer_view": True, "scenarios": None}
        shown = set(analysis["shown_accounts"])
        merged, _, entries = self._merged(analysis["customer"], only=shown)
        # A parent's workbook covers its affiliates' enrollments too -- the ones shown.
        exported = {**analysis["customer"],
                    "accounts": [account for account in analysis["group"]["accounts"] if account["name"] in shown]}
        analysis = {**analysis, "marketplace": self.marketplace(customer_id, "start", None)}
        workbook = export_xlsx.build(exported, analysis, merged, self._today(), entries)
        audience = " - for the customer" if view == "customer" else ""
        return f"Azure consumption - {analysis['customer']['name']}{audience} - {self._today().isoformat()}.xlsx", workbook

    def drill(self, customer_id: str, kind: str, name: str, accounts: list[str] | None = None) -> dict:
        """One service, subscription, solution play or month of a customer, opened up
        (operator, 2026-10-23: "any text can be drilled down")."""
        customer = self._customer(customer_id)
        merged, currency, entries = self._merged(customer, only=set(accounts) if accounts else None)
        groups: dict[str, float] = {}
        if kind == "subscription":
            for entry in entries.values():
                footprint = entry.get("footprint") or {}
                found = (footprint.get("subscriptions") or {}).get(name) or {}
                for group, cost in (found.get("resource_groups") or {}).items():
                    groups[group] = groups.get(group, 0.0) + cost / (footprint.get("months") or 1)
        found = drill.analyse(merged, kind, name, months.month_of(self._today()), self.solution_play_mapping(), groups)
        notes = self._technology_notes
        if kind == "service":
            found["technology_note"] = notes.note_for(name) if notes else None
            found["solutions"] = [{"id": pattern["id"], "name": pattern["name"], "note": pattern.get("note")}
                                  for pattern in self._patterns()
                                  if f"service:{name}" in {signal for group in pattern["requires"] for signal in group}
                                  | set(pattern["supports"])]
        if found.get("pairs_missing") and not found["parts"] and kind in ("service", "subscription"):
            found.update(parts=drill.from_footprints(entries, kind, name), from_footprint=True)
        if kind == "service" and name in MARKETPLACE_SERVICES:
            found["marketplace"] = self._marketplace_behind(entries, found["recent_months"])
        if found.get("parts_kind") == "service" and notes:
            for row in found["parts"]:
                row["technology_note"] = notes.note_for(row["name"])
        if kind == "subscription":
            row = next((row for row in self.solutions_of(customer_id)["subscriptions"] if row["subscription"] == name), None)
            found["solutions"] = [{"id": item["id"], "name": item["name"], "note": item.get("note")}
                                  for item in (row["solutions"] + row["also"])] if row else []
        return {"customer": {"id": customer["id"], "name": customer["name"]}, "currency": currency, **found}

    @staticmethod
    def _marketplace_behind(entries: dict[str, dict], recent: list[str]) -> list[dict]:
        """What "SaaS" and "Azure Applications" are (operator, 2026-10-23: "the word SaaS ... I
        need a way to know what it is"): Cost Management bills every Marketplace SaaS offer
        as one service; the month's Marketplace charges name each publisher, offer and plan."""
        found: dict[tuple, dict] = {}
        for entry in entries.values():
            for month in recent:
                for item in (((entry.get("months") or {}).get(month) or {}).get("marketplace") or {}).get("items") or []:
                    key = (item["publisher"], item["offer"], item.get("plan") or "")
                    row = found.setdefault(key, {"publisher": key[0], "offer": key[1], "plan": key[2],
                                                 "subscriptions": set(), "cost": 0.0, "recurring": item.get("recurring")})
                    row["cost"] += item["cost"]
                    if item.get("subscription"):
                        row["subscriptions"].add(item["subscription"])
        rows = [{**{key: value for key, value in row.items() if key != "cost"},
                 "monthly": round(row["cost"] / max(1, len(recent)), 2),
                 "subscriptions": sorted(row["subscriptions"])} for row in found.values()
                if row["cost"] / max(1, len(recent)) >= 0.5]
        return sorted(rows, key=lambda row: -row["monthly"])

    def consumption(self, customer_id: str, first_month: str | None, last_month: str | None,
                    group_by: str, cost_kind: str, accounts: list[str] | None = None) -> dict:
        """Spend per month per `service`, `subscription`, `account` (enrollment) or `play`
        (solution play), for the group's enrollments or just `accounts` of them."""
        if group_by not in ("service", "subscription", "account", "play"):
            raise ValueError("group must be 'service', 'subscription', 'account' or 'play'")
        if cost_kind not in consumption_analysis.COST_KINDS:
            raise ValueError("cost must be 'actual' or 'amortized'")
        merged, _, _ = self._merged(self._customer(customer_id), only=set(accounts) if accounts else None)
        plays = self.solution_play_mapping() if group_by == "play" else {}
        rows = []
        for month in sorted(merged):
            if (first_month and month < first_month) or (last_month and month > last_month):
                continue
            spend = (solution_plays.split(merged[month][cost_kind]["service"], merged[month].get("meters"), plays,
                                          (merged[month].get("measured") or {}).get("marketplace"))
                     if group_by == "play" else merged[month][cost_kind][group_by])
            rows.extend({"month": month, "name": name, "cost": round(cost, 2)}
                        for name, cost in sorted(spend.items(), key=lambda item: -item[1]))
        return {"customer": customer_id, "group": group_by, "cost": cost_kind, "rows": rows}
