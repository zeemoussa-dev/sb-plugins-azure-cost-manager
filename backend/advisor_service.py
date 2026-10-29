"""Gathers the facts for the seller's Compass features from the reports the plugin
already computes, asks Compass, and keeps what is worth keeping (`advisor`,
`compass`). Nothing here computes a figure of its own."""
from __future__ import annotations

import os
from datetime import date

from . import advisor, compass, customer_profile, focus_analysis, personas, use_cases

ACTIONS_FOR = 30
MARKETPLACE_BATCH = 40


class Advisor:
    def __init__(self, service, answers: compass.Answers, llm) -> None:
        self._service = service
        self._answers = answers
        self._llm = llm

    def available(self) -> bool:
        return bool(self._llm and self._llm.available())

    def _ask(self, feature: str, messages: list[dict]) -> str:
        """Compass, speaking as the feature's persona (`personas`)."""
        return compass.ask(self._llm, personas.apply(messages, self._service.personas.for_feature(feature)))

    def _stamp(self, feature: str, facts) -> str:
        # The persona is part of what an answer was written from: editing it makes the answer stale.
        return compass.fingerprint({"facts": facts, "persona": self._service.personas.for_feature(feature)})

    def _kept(self, kind: str, key: str, stamp: str) -> dict:
        kept = self._answers.get(kind, key)
        return {"value": kept["value"] if kept else None, "at": kept["at"] if kept else None, "kept": bool(kept),
                "stale": bool(kept) and kept["fingerprint"] != stamp, "available": self.available()}

    # -- explain a move -------------------------------------------------------------

    def explain(self, customer_id: str, kind: str, name: str, write: bool = False,
                accounts: list[str] | None = None, note: str | None = None) -> dict:
        """`note`: the seller's answer to the question Compass asked, or what they know --
        kept with the item and handed to every explanation of it from then on (operator,
        2026-10-23: "Explain this asks me a question but I have no option to answer")."""
        key, about = f"{customer_id}|{kind}|{name}", f"explain: {kind} {name}"
        if note and note.strip():
            compass.require(self._llm)
            # Into the customer's memory: the brief and every other feature hear it too.
            self._service.memory.add(customer_id, note, about)
            write = True
        facts = advisor.explain_facts(self._service.drill(customer_id, kind, name, accounts),
                                      self._service.current_month(), self._service.memory.handed(customer_id),
                                      self._service.industry_of(customer_id))
        stamp = self._stamp("explain", facts)
        if write:
            text = self._ask("explain", advisor.explain_messages(facts))
            self._answers.put("explain", key, stamp, text.strip())
        return {**self._kept("explain", key, stamp),
                "notes": [line for line in self._service.memory.of(customer_id) if line.get("source") == about]}

    # -- one slice of the bill, analysed ---------------------------------------------

    def focus(self, customer_id: str, focus: dict, write: bool = False, accounts: list[str] | None = None) -> dict:
        """The Analysis tab (operator, 2026-10-29): the figures for the chosen services,
        subscriptions and groups, and Compass's reading of them -- kept per customer
        and choice until what it was written from changes."""
        found = self._service.focus(customer_id, focus, accounts)
        candidates = [{"meter": item["meter"], "monthly_on_demand": item["monthly_on_demand"],
                       "savings_monthly_by_option": item.get("savings")}
                      for item in self._service.finops(customer_id, accounts, waste=False).get("candidates") or []]
        facts = focus_analysis.facts(found["customer"]["name"], found["currency"], found["focus"], found["groups"],
                                     found["figures"], found["built_from"], found["tags"],
                                     self._service.brief_facts(customer_id), candidates, found["solutions"],
                                     self._service.industry_of(customer_id))
        key = f"{customer_id}|{','.join(accounts or [])}|{found['key']}"
        stamp = self._stamp("focus", facts)
        if write:
            answer = focus_analysis.check(self._ask("focus", focus_analysis.messages(
                facts, advisor.RULES, advisor.INDUSTRY_RULE, advisor.CONTEXT_RULE)))
            self._answers.put("focus", key, stamp, {**answer, "title": found["title"], "focus": found["focus"]})
        return {**{name: found[name] for name in ("customer", "currency", "focus", "title", "figures", "built_from",
                                                  "tags", "solutions")},
                "industry": (self._service.industry_of(customer_id) or {}).get("industry"),
                "answer": self._kept("focus", key, stamp)}

    def focus_kept(self, customer_id: str) -> list[dict]:
        """The analyses kept for a customer, newest first: what the tab offers to reopen."""
        kept = self._answers.listed("focus")
        return sorted(({"title": item["value"].get("title"), "focus": item["value"].get("focus"), "at": item["at"],
                        "accounts": [name for name in key.split("|")[1].split(",") if name]}
                       for key, item in kept.items() if key.split("|")[0] == customer_id and item.get("value")),
                      key=lambda row: row["at"] or "", reverse=True)

    # -- next best actions --------------------------------------------------------

    def _pitches_by_customer(self) -> dict[str, list[dict]]:
        sizing = {pattern["name"]: [pattern["sizing"]["totals"][size] for size in advisor.SIZES]
                  for pattern in self._service.solution_catalog()["patterns"] if pattern.get("sizing")}
        found: dict[str, list[dict]] = {}
        for item in self._service.solutions_across()["pitches"]:
            found.setdefault(item["customer_id"], [])
            if len(found[item["customer_id"]]) < 3:
                found[item["customer_id"]].append({"pitch": item["pitch"], "solution": item["solution"],
                                                   "sized_monthly": sizing.get(item["solution"])})
        return found

    def _action_facts(self) -> dict:
        portfolio = self._service.portfolio()
        top = sorted((row for row in portfolio if not row.get("parent")),
                     key=lambda row: -((row.get("last_month") or {}).get("actual") or 0))[:ACTIONS_FOR]
        pipeline = {}
        for row in top:
            state = self._service.pipeline(row["id"])
            open_items = [item for item in state.get("opportunities") or [] if item.get("status") in (None, "Open")]
            if open_items:
                pipeline[row["id"]] = {"open": len(open_items), "expected_monthly": round(sum(
                    float(item.get("expected_monthly_usd") or 0) for item in open_items))}
        growth = {row["id"]: row for row in self._service.growth_across()}
        said = {row["id"]: self._service.memory.handed(row["id"])[-3:] for row in top
                if self._service.memory.of(row["id"])}
        renewing = {}
        for row in top:
            soon = [item for item in self._service.finops(row["id"], waste=False).get("renewals") or [] if item["soon"]]
            if soon:
                renewing[row["id"]] = soon
        return advisor.action_facts(portfolio, growth, self._service.quota_across(), self._pitches_by_customer(),
                                    pipeline, ACTIONS_FOR, said, renewing, self._service.industry_names())

    def actions(self, write: bool = False) -> dict:
        facts = self._action_facts()
        stamp = self._stamp("actions", facts)
        if write:
            ranked = advisor.check_actions(self._ask("actions", advisor.action_messages(facts)), facts)
            self._answers.put("actions", "all", stamp, ranked)
        return self._kept("actions", "all", stamp)

    # -- what to pitch --------------------------------------------------------------

    def pitches(self, customer_id: str, write: bool = False) -> dict:
        """Compass's recommendations of what to pitch, beyond the rules' (operator,
        2026-10-23), kept until the customer's facts move."""
        facts = advisor.pitch_facts(self._service.brief_facts(customer_id),
                                    self._service.solution_catalog()["patterns"], self._service.playbooks())
        stamp = self._stamp("pitches", facts)
        if write:
            found = advisor.check_pitches(self._ask("pitches", advisor.pitch_messages(facts)), facts)
            self._answers.put("pitches", customer_id, stamp, found)
        return {**self._kept("pitches", customer_id, stamp), "industry": facts["industry"].get("industry"),
                "industry_missing": facts["industry"].get("missing")}

    # -- where the customer stands ---------------------------------------------------

    def draft_context(self, customer_id: str) -> dict:
        """Compass's draft of the customer's context, shown for the seller to correct and
        save -- never saved by itself."""
        facts = advisor.context_facts(self._service.brief_facts(customer_id))
        reply = self._ask("context", advisor.context_messages(facts, customer_profile.FIELDS))
        return {"draft": advisor.check_context(reply, customer_profile.KEYS)}

    # -- an industry use case, in detail -------------------------------------------

    def _kept_pitch(self, customer_id: str, pitch_text: str) -> dict:
        kept = (self._answers.get("pitches", customer_id) or {}).get("value") or []
        pitch = next((item for item in kept if item["pitch"] == pitch_text), None)
        if not pitch:
            raise ValueError("that pitch is not one Compass recommended for this customer")
        return pitch

    def use_case(self, customer_id: str, pitch_text: str, write: bool = False) -> dict:
        """The drill-down on a Compass pitch (operator, 2026-10-24): the use case written
        out -- the part about the industry is what a use-case note would hold, the part
        about this customer stays here -- kept until what it was written from changes."""
        pitch = self._kept_pitch(customer_id, pitch_text)
        solution = next((pattern for pattern in self._service.solution_catalog()["patterns"]
                         if pattern["id"] == pitch.get("solution_id")), None)
        brief_facts = self._service.brief_facts(customer_id)
        running = self._service.services_running(customer_id)
        facts = advisor.use_case_facts(brief_facts, pitch, solution,
                                       sorted(running, key=lambda name: -running[name])[:60])
        key, stamp = f"{customer_id}|{pitch_text}", self._stamp("use-case", facts)
        if write:
            self._answers.put("use-case", key, stamp, advisor.check_use_case(
                self._ask("use-case", advisor.use_case_messages(facts)), facts))
        industry = (brief_facts.get("industry") or {}).get("industry")
        kept = self._kept("use-case", key, stamp)
        preview = None
        if kept["value"] and industry:
            preview = use_cases.markdown(kept["value"]["note"], industry,
                                         [solution["note"]] if (solution or {}).get("note") else [], date.today().isoformat())
        # Read against the bill each time, not kept: what the customer runs moves on its own.
        status = use_cases.on_the_bill(kept["value"]["note"].get("expected_services") or [], running) if kept["value"] else {}
        return {**kept, "industry": industry, "industry_note": bool(industry and self._service.industry_note_path(industry)),
                "use_case_note": pitch.get("use_case_note"), "solution_note": (solution or {}).get("note"),
                "note_markdown": preview, "on_the_bill": status}

    def publish_use_case(self, customer_id: str, pitch_text: str) -> dict:
        """Files the drafted use case as a note beside its Industry note (operator: "publish
        to vault" on the seller's click), then links the pitch to it."""
        found = self.use_case(customer_id, pitch_text)
        if not found["value"]:
            raise ValueError("write the use case first")
        if found["use_case_note"]:
            raise ValueError(f"this use case is already in the vault as {found['use_case_note']}")
        industry = found["industry"]
        path = self._service.industry_note_path(industry) if industry else None
        if not path:
            raise ValueError("set the customer's industry, with an Industry note in the vault, to file a use case under it"
                             if not industry else f"there is no Industry note called {industry} to file it beside")
        name = found["value"]["note"]["name"]
        try:
            written = use_cases.write_new(path, name, found["note_markdown"])
        except use_cases.UseCaseExists as exc:
            raise ValueError(str(exc)) from exc
        stem = os.path.splitext(os.path.basename(written))[0]
        # The pitch now links its note, as one matched from the vault would.
        kept = self._answers.get("pitches", customer_id)
        self._answers.put("pitches", customer_id, kept["fingerprint"],
                          [{**item, "use_case_note": stem} if item["pitch"] == pitch_text else item for item in kept["value"]])
        return {**found, "use_case_note": stem, "published": written}

    # -- draft from a pitch --------------------------------------------------------

    def draft(self, customer_id: str, pitch_text: str) -> dict:
        view = self._service.solutions_of(customer_id)
        pitch = next((item for item in view["pitches"] if item["pitch"] == pitch_text), None)
        if not pitch:
            # One Compass recommended (kept), drafted the same way as a rule's.
            kept = (self._answers.get("pitches", customer_id) or {}).get("value") or []
            pitch = next(({"pitch": item["pitch"], "solution": item["solution"], "play": item["play"],
                           "subscriptions": [], "use_case": item.get("use_case"),
                           "business_outcome": item.get("business_outcome"),
                           "business_owner": item.get("business_owner")}
                          for item in kept if item["pitch"] == pitch_text), None)
        if not pitch:
            raise ValueError("that pitch is not one this customer is shown")
        sizing = next((pattern.get("sizing") for pattern in self._service.solution_catalog()["patterns"]
                       if pattern["name"] == pitch["solution"]), None)
        running = next((item for item in view["solutions"] if item["name"] == pitch["solution"]), {})
        facts = advisor.draft_facts(self._service.brief_facts(customer_id), pitch, sizing, running.get("monthly"))
        return {**advisor.check_draft(self._ask("draft", advisor.draft_messages(facts)), facts),
                "solution": pitch["solution"], "customer_view": self._customer_view(customer_id, pitch_text)}

    def _customer_view(self, customer_id: str, pitch_text: str) -> str | None:
        """The customer's side of the pitch's use case, when one was written: what the
        opportunity drafted from it carries (operator, 2026-10-25: "the customer view
        needs to be part of the opportunity if the seller converts it")."""
        kept = (self._answers.get("pitches", customer_id) or {}).get("value") or []
        if not any(item["pitch"] == pitch_text for item in kept):
            return None
        found = (self._answers.get("use-case", f"{customer_id}|{pitch_text}") or {}).get("value")
        if not found:
            return None
        status = use_cases.on_the_bill(found["note"].get("expected_services") or [],
                                       self._service.services_running(customer_id))
        return use_cases.customer_view(found, status, self._service.customer(customer_id)["name"])

    # -- FinOps ---------------------------------------------------------------------

    def _finops_facts(self, customer_id: str, customer_view: bool, accounts: list[str] | None) -> dict:
        found = self._service.finops(customer_id, accounts)
        return advisor.finops_facts(found, None if customer_view else self._service.brief_facts(customer_id), customer_view,
                                    self._service.industry_of(customer_id))

    def finops_plan(self, customer_id: str, write: bool = False, accounts: list[str] | None = None) -> dict:
        """Compass's savings plan over the FinOps findings (operator, 2026-10-24): commit,
        hold or investigate, the risk of each, and savings told as money to reinvest."""
        facts = self._finops_facts(customer_id, False, accounts)
        stamp, key = self._stamp("finops-plan", facts), f"{customer_id}|{','.join(accounts or [])}"
        if write:
            plan = advisor.check_finops_plan(self._ask("finops-plan", advisor.finops_plan_messages(facts)), facts)
            self._answers.put("finops-plan", key, stamp, plan)
        return self._kept("finops-plan", key, stamp)

    def finops_report(self, customer_id: str, write: bool = False, accounts: list[str] | None = None) -> dict:
        """The savings report to hand the customer: their own findings only, nothing internal."""
        facts = self._finops_facts(customer_id, True, accounts)
        stamp, key = self._stamp("finops-report", facts), f"{customer_id}|{','.join(accounts or [])}"
        if write:
            text = self._ask("finops-report", advisor.finops_report_messages(facts))
            self._answers.put("finops-report", key, stamp, text.strip())
        return self._kept("finops-report", key, stamp)

    # -- tagging --------------------------------------------------------------------

    def _tagging_facts(self, customer_id: str, customer_view: bool, accounts: list[str] | None) -> dict:
        found = self._service.tags(customer_id, accounts)
        return advisor.tagging_facts(found, None if customer_view else self._service.brief_facts(customer_id), customer_view,
                                     self._service.industry_of(customer_id))

    def tagging_plan(self, customer_id: str, write: bool = False, accounts: list[str] | None = None) -> dict:
        """Compass's tagging plan over the gaps (operator, 2026-10-24): which keys and values
        to standardize, what inheritance and policy fill, in order of coverage for effort."""
        facts = self._tagging_facts(customer_id, False, accounts)
        stamp, key = self._stamp("tagging-plan", facts), f"{customer_id}|{','.join(accounts or [])}"
        if write:
            plan = advisor.check_tagging_plan(self._ask("tagging-plan", advisor.tagging_plan_messages(facts)), facts)
            self._answers.put("tagging-plan", key, stamp, plan)
        return self._kept("tagging-plan", key, stamp)

    def tagging_guide(self, customer_id: str, write: bool = False, accounts: list[str] | None = None) -> dict:
        """Tagging guidance to hand the customer: their own gaps only, nothing internal."""
        facts = self._tagging_facts(customer_id, True, accounts)
        stamp, key = self._stamp("tagging-guide", facts), f"{customer_id}|{','.join(accounts or [])}"
        if write:
            text = self._ask("tagging-guide", advisor.tagging_guide_messages(facts))
            self._answers.put("tagging-guide", key, stamp, text.strip())
        return self._kept("tagging-guide", key, stamp)

    # -- size a solution -----------------------------------------------------------

    def size(self, solution_id: str, answers: str, customer_id: str | None = None) -> dict:
        solution = next((pattern for pattern in self._service.solution_catalog()["patterns"]
                         if pattern["id"] == solution_id), None)
        if not solution or not solution.get("sizing"):
            raise ValueError("that solution has no sizing table in its note")
        if not answers.strip():
            raise ValueError("say what you know about the customer's needs: users, data, requests, environments")
        customer = None
        if customer_id:
            facts = self._service.brief_facts(customer_id)
            customer = {"name": facts["customer"], "consumption": facts["consumption"].get("monthly_run_rate_3m"),
                        "seller_says": facts.get("seller_says"),
                        "industry": (facts.get("industry") or {}).get("industry")}
        reply = self._ask("size", advisor.sizing_messages(solution, answers, customer))
        return {"solution": solution["name"], "note": solution.get("note"),
                **advisor.check_sizing(reply, solution["sizing"])}

    # -- ask your data -------------------------------------------------------------

    def ask(self, question: str) -> dict:
        question = question.strip()
        if not question:
            raise ValueError("ask a question")
        cache: dict = {}

        def guide() -> dict:
            if "guide" not in cache:
                cache["guide"] = self._service.guide()
            return cache["guide"]

        catalog = self._service.solution_catalog()["patterns"]
        plan = advisor.check_plan(self._ask("ask", advisor.plan_messages(
            question, [item["name"] for item in guide()["services"] if item["customers"]],
            [pattern["name"] for pattern in catalog])))
        results = [{"report": call["tool"], "args": call["args"], "rows": self._run(call, guide)} for call in plan]
        answer = self._ask("ask", advisor.answer_messages(question, results)) if results else \
            "None of the reports answers that. Try asking about services, solutions, growth, MACCs, quota or Marketplace."
        return {"question": question, "answer": answer.strip(), "calls": results}

    def _run(self, call: dict, guide) -> list[dict] | dict:
        args = call["args"]
        services = {item["name"].lower(): item for item in guide()["services"]}

        def users(name: str) -> set[str]:
            return {customer["name"] for customer in (services.get(str(name).lower()) or {}).get("customers") or []}

        if call["tool"] == "customers_using_service":
            item = services.get(str(args.get("service") or "").lower())
            return item["customers"][:25] if item else []
        if call["tool"] == "customers_running_solution":
            wanted = str(args.get("solution") or "").lower()
            item = next((row for row in self._service.solutions_across()["by_solution"] if row["name"].lower() == wanted), None)
            return {"customers": item["customers"], "subscriptions": item["subscriptions"],
                    "monthly_in_them": item["monthly"]} if item else []
        if call["tool"] == "customers_with_but_without":
            return sorted(users(args.get("has") or "") - users(args.get("lacks") or ""))[:40]
        if call["tool"] == "growth":
            status = "declining" if args.get("direction") == "declining" else "growing"
            return [{"customer": row["name"], "last_month": row.get("last_total"), "change_3m_pct": row.get("change_3m_pct")}
                    for row in self._service.growth_across() if row.get("status") == status][:20]
        if call["tool"] == "macc_status":
            return [{"customer": row["name"], "signed": row.get("signed"), **{key: (row.get("burn") or {}).get(key) for key in
                     ("consumed_pct", "elapsed_pct", "projected_exhaustion", "projected_shortfall", "end")}}
                    for row in self._service.portfolio() if row.get("burn") and not row.get("parent")][:40]
        if call["tool"] == "customer_summary":
            wanted = str(args.get("customer") or "").lower()
            customer = next((row for row in self._service.portfolio() if wanted and wanted in row["name"].lower()), None)
            if not customer:
                return []
            facts = self._service.brief_facts(customer["id"])
            return {key: facts.get(key) for key in ("customer", "consumption", "commitment", "solutions", "pitches", "pipeline")}
        if call["tool"] == "marketplace_buyers":
            words = str(args.get("text") or "").lower()
            return [{**{key: product[key] for key in ("publisher", "offer", "plan", "monthly")},
                     "customers": [customer["name"] for customer in product["customers"]]}
                    for product in (services.get("saas") or {}).get("marketplace") or []
                    if words and words in f"{product['publisher']} {product['offer']} {product['plan']}".lower()][:20]
        if call["tool"] == "customers_by_industry":
            wanted = str(args.get("industry") or "").strip().lower()
            names = self._service.industry_names()
            rows = [{"customer": row["name"], "industry": names.get(row["id"]) or "not set",
                     "last_month": round((row.get("last_month") or {}).get("actual") or 0)}
                    for row in self._service.portfolio() if not row.get("parent")]
            return sorted([row for row in rows if not wanted or wanted in row["industry"].lower()],
                          key=lambda row: (row["industry"], -row["last_month"]))[:60]
        if call["tool"] == "tag_coverage":
            return [{"customer": row["name"], "tag_keys": row["tag_keys"], "coverage_pct": row["coverage"],
                     "spellings_per_dimension": row["spellings"]}
                    for row in self._service.tags_across() if row["synced"]][:30]
        if call["tool"] == "savings_candidates":
            return [{"customer": row["name"], "steady_on_demand_monthly": row["candidates_monthly"],
                     "coverage_pct": row["coverage_pct"], "saving_monthly_by_option": row["savings_monthly"],
                     "top_candidate": row["top_candidate"]}
                    for row in self._service.finops_across() if row["candidates_monthly"]][:20]
        if call["tool"] in ("hybrid_benefit", "commitment_renewals"):
            rows = []
            for customer in [row for row in self._service.portfolio() if not row.get("parent")][:30]:
                found = self._service.finops(customer["id"], waste=False)
                if call["tool"] == "hybrid_benefit" and found.get("hybrid_benefit"):
                    rows.append({"customer": customer["name"], "licenses": [{"product": item["product"],
                                 "monthly": item["monthly"]} for item in found["hybrid_benefit"]]})
                if call["tool"] == "commitment_renewals" and any(item["soon"] for item in found.get("renewals") or []):
                    rows.append({"customer": customer["name"],
                                 "renewing": [item for item in found["renewals"] if item["soon"]]})
            return rows
        if call["tool"] == "quota":
            found = self._service.quota_across()
            return {**{key: found.get(key) for key in ("above_projected", "gap_to_quota", "projected_pct")},
                    "customers": [{"customer": row["name"], "above_projected": row.get("above_projected")}
                                  for row in sorted(found.get("customers") or [],
                                                    key=lambda row: -(row.get("above_projected") or 0))[:15]]}
        return []

    # -- personas ------------------------------------------------------------------

    def personas(self) -> dict:
        return {"personas": self._service.personas.listed(), "available": self.available(),
                "industries": self._service.industries()}

    def generate_persona(self, persona_id: str, wish: str) -> dict:
        """Compass drafts a persona for the seller to read, change and save -- never saved by itself."""
        if persona_id not in personas.PERSONAS:
            raise ValueError("no such persona")
        draft = compass.ask(self._llm, personas.generate_messages(
            persona_id, self._service.personas.prompt(persona_id), wish or "", self._service.industries()))
        return {"draft": draft.strip()[:personas.LONGEST]}

    # -- Marketplace products --------------------------------------------------------

    @staticmethod
    def _product_key(product: dict) -> str:
        return f"{product['publisher']}|{product['offer']}|{product['plan']}"

    def marketplace(self, write: bool = False) -> dict:
        services = {item["name"]: item for item in self._service.guide()["services"]}
        products = [product for name in ("SaaS", "Azure Applications")
                    for product in (services.get(name) or {}).get("marketplace") or []]
        keys = {self._product_key(product): product for product in products}
        known = {key: kept["value"] for key in keys if (kept := self._answers.get("marketplace", key))}
        if write:
            unknown = [key for key in keys if key not in known]
            for start in range(0, len(unknown), MARKETPLACE_BATCH):
                batch = unknown[start:start + MARKETPLACE_BATCH]
                reply = compass.ask(self._llm, advisor.marketplace_messages(
                    [{"key": key, "publisher": keys[key]["publisher"], "offer": keys[key]["offer"],
                      "plan": keys[key]["plan"]} for key in batch]))
                for key, value in advisor.check_marketplace(reply, set(batch)).items():
                    self._answers.put("marketplace", key, key, value)
                    known[key] = value
        return {"available": self.available(), "classified": known, "products": len(keys),
                "pending": len([key for key in keys if key not in known])}
