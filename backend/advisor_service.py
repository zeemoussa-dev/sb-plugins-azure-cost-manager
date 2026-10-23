"""Gathers the facts for the seller's Compass features from the reports the plugin
already computes, asks Compass, and keeps what is worth keeping (`advisor`,
`compass`). Nothing here computes a figure of its own."""
from __future__ import annotations

from . import advisor, compass

ACTIONS_FOR = 30
MARKETPLACE_BATCH = 40


class Advisor:
    def __init__(self, service, answers: compass.Answers, llm) -> None:
        self._service = service
        self._answers = answers
        self._llm = llm

    def available(self) -> bool:
        return bool(self._llm and self._llm.available())

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
                                      self._service.current_month(), self._service.memory.handed(customer_id))
        stamp = compass.fingerprint(facts)
        if write:
            text = compass.ask(self._llm, advisor.explain_messages(facts))
            self._answers.put("explain", key, stamp, text.strip())
        return {**self._kept("explain", key, stamp),
                "notes": [line for line in self._service.memory.of(customer_id) if line.get("source") == about]}

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
        return advisor.action_facts(portfolio, growth, self._service.quota_across(), self._pitches_by_customer(),
                                    pipeline, ACTIONS_FOR, said)

    def actions(self, write: bool = False) -> dict:
        facts = self._action_facts()
        stamp = compass.fingerprint(facts)
        if write:
            ranked = advisor.check_actions(compass.ask(self._llm, advisor.action_messages(facts)), facts)
            self._answers.put("actions", "all", stamp, ranked)
        return self._kept("actions", "all", stamp)

    # -- draft from a pitch --------------------------------------------------------

    def draft(self, customer_id: str, pitch_text: str) -> dict:
        view = self._service.solutions_of(customer_id)
        pitch = next((item for item in view["pitches"] if item["pitch"] == pitch_text), None)
        if not pitch:
            raise ValueError("that pitch is not one this customer is shown")
        sizing = next((pattern.get("sizing") for pattern in self._service.solution_catalog()["patterns"]
                       if pattern["name"] == pitch["solution"]), None)
        running = next((item for item in view["solutions"] if item["name"] == pitch["solution"]), {})
        facts = advisor.draft_facts(self._service.brief_facts(customer_id), pitch, sizing, running.get("monthly"))
        return {**advisor.check_draft(compass.ask(self._llm, advisor.draft_messages(facts)), facts),
                "solution": pitch["solution"]}

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
                        "seller_says": facts.get("seller_says")}
        reply = compass.ask(self._llm, advisor.sizing_messages(solution, answers, customer))
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
        plan = advisor.check_plan(compass.ask(self._llm, advisor.plan_messages(
            question, [item["name"] for item in guide()["services"] if item["customers"]],
            [pattern["name"] for pattern in catalog])))
        results = [{"report": call["tool"], "args": call["args"], "rows": self._run(call, guide)} for call in plan]
        answer = compass.ask(self._llm, advisor.answer_messages(question, results)) if results else \
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
        if call["tool"] == "quota":
            found = self._service.quota_across()
            return {**{key: found.get(key) for key in ("above_projected", "gap_to_quota", "projected_pct")},
                    "customers": [{"customer": row["name"], "above_projected": row.get("above_projected")}
                                  for row in sorted(found.get("customers") or [],
                                                    key=lambda row: -(row.get("above_projected") or 0))[:15]]}
        return []

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
