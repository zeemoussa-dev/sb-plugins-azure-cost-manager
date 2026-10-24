"""The seller's Compass features beyond the brief and placements (operator,
2026-10-23): explaining a move, the next best actions across customers, drafting
from a pitch, sizing a solution, answering a question from the reports, and
saying what a Marketplace product is.

Pure: facts in, prompt out, Compass's answer checked. Every figure a seller sees
is one the plugin computed -- a model's number is never shown as a fact.
"""
from __future__ import annotations

from . import brief, compass
from .industry import short as industry_short

RULES = (
    "Use ONLY the facts given. Never invent a number, a date, a person, a product or an event; quote figures as "
    "given (you may round them, e.g. $1.2M). When the facts do not say, say so. Write for a Core42 seller who sells "
    "Azure consumption against the customer's MACC and Core42's own offers, including Compass by Core42 (sovereign, "
    "in-country AI models). Be specific and brief."
)
# Every feature handed the customer's industry (`industry`) reads it this way.
INDUSTRY_RULE = ("'industry' is what the customer's Industry note says; bring it in where the facts "
                 "meet it, never as a claim about this customer the facts do not support.")
SIZES = ("small", "medium", "large")
URGENCY = ("now", "this quarter", "later")


def _system(task: str) -> dict:
    return {"role": "system", "content": f"{task}\n\nRules:\n- {RULES}"}


# -- explain a move ----------------------------------------------------------------

def explain_facts(drill: dict, current_month: str | None = None, seller_notes: list[dict] | None = None,
                  industry: dict | None = None) -> dict:
    """`seller_notes`: the customer's memory -- what the seller told Compass about it."""
    # The month still being billed is marked: read as a whole month, a third of one
    # looked like a fall (checked on ADNOC's Foundry Models, 2026-10-23).
    trend = [{**point, **({"partial": "billed so far, month not over"} if point["month"] == current_month else {})}
             for point in drill.get("trend") or [] if point.get("cost")][-8:]
    return {key: value for key, value in {
        "customer": (drill.get("customer") or {}).get("name"), "kind": drill.get("kind"), "name": drill.get("name"),
        "currency": drill.get("currency"), "by_month": trend,
        "made_of": (drill.get("parts") or [])[:12], "made_of_kind": drill.get("parts_kind"),
        "resource_groups": drill.get("resource_groups"), "marketplace_products": (drill.get("marketplace") or [])[:10],
        "solutions": [item.get("name") for item in drill.get("solutions") or []],
        "subscriptions_that_month": (drill.get("subscriptions") or [])[:12], "by_play": drill.get("by_play"),
        "previous_month": drill.get("previous"), "total": drill.get("total"),
        # What the seller has told us about this item -- the customer's answers, or their own knowledge.
        "seller_says": seller_notes,
        "industry": industry_short(industry) if (industry or {}).get("industry") else None,
    }.items() if value not in (None, [], {})}


def explain_messages(facts: dict) -> list[dict]:
    return [_system(
        "Explain to the seller what this item of a customer's Azure bill is doing: what moved and when, where it "
        "moved (which of the parts it is made of), the most likely reason the facts support, and the one question "
        "to ask the customer. Monthly figures are monthly averages of the last closed months unless a month is "
        "named; 'last_12' is a twelve-month total. A month marked partial is still being billed: never read it as "
        "a fall. 'seller_says' is what the seller has learned (often the customer's answer to an earlier "
        "question): treat it as fact, let it replace a guessed reason, and do not ask again what it already "
        "answers. Markdown, at most 140 words, no headings: two or three short paragraphs, then a last line "
        "starting exactly '**Ask the customer:**' with the one question still worth asking -- or, when "
        "seller_says leaves nothing to ask, '**Next:**' with what the seller should do. "
        "When the customer's industry has a reason for such a move (a regulatory programme, a reporting cycle), "
        "name it as a possibility -- " + INDUSTRY_RULE),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


# -- next best actions -------------------------------------------------------------

def action_facts(portfolio: list[dict], growth: dict[str, dict], quota: dict, pitches: dict[str, list[dict]],
                 pipeline: dict[str, dict], limit: int = 30, seller_says: dict[str, list[dict]] | None = None,
                 renewals: dict[str, list[dict]] | None = None, industries: dict[str, str | None] | None = None) -> dict:
    """One line per top-level customer, the largest last month first, and the seller's quota."""
    rows = []
    for row in sorted((item for item in portfolio if not item.get("parent")),
                      key=lambda item: -((item.get("last_month") or {}).get("actual") or 0))[:limit]:
        burn = row.get("burn") or {}
        moved = growth.get(row["id"]) or {}
        above = next((item for item in quota.get("customers") or [] if item["id"] == row["id"]), {})
        rows.append({key: value for key, value in {
            "customer_id": row["id"], "customer": row["name"], "industry": (industries or {}).get(row["id"]),
            "last_month": round((row.get("last_month") or {}).get("actual") or 0),
            "change_3m_pct": moved.get("change_3m_pct"), "change_12m_pct": moved.get("change_12m_pct"),
            "signals": [signal.get("text") for signal in moved.get("signals") or []][:3],
            "macc": {"signed": row.get("signed"), "consumed_pct": burn.get("consumed_pct"),
                     "elapsed_pct": burn.get("elapsed_pct"), "runs_out": burn.get("projected_exhaustion"),
                     "shortfall_at_end": burn.get("projected_shortfall"), "ends": burn.get("end")} if burn else None,
            "above_baseline_projected": round(above["above_projected"]) if above.get("above_projected") is not None else None,
            "pitches": pitches.get(row["id"]) or [],
            "open_pipeline": pipeline.get(row["id"]),
            "commitments_may_renew": (renewals or {}).get(row["id"]),
            "seller_says": (seller_says or {}).get(row["id"]),
        }.items() if value not in (None, [], {})})
    return {"quota": {key: quota.get(key) for key in ("above_projected", "gap_to_quota", "projected_pct")},
            "customers": rows}


def action_messages(facts: dict) -> list[dict]:
    return [_system(
        "Rank the seller's next best actions across these customers -- the ones most worth doing this week for "
        "the customer, the MACC and the seller's quota. Consider: a MACC running out before its end (renewal or "
        "top-up), a MACC heading for a shortfall (consumption to grow), sharp growth or decline, pitches with "
        "their sizing, thin pipeline, and commitments that may renew soon (a renewal conversation). A customer's "
        "'seller_says' is what the seller told you: treat it as "
        "fact (a MACC already renewed needs no renewal action). Word each action for the customer's industry "
        "where it is given -- what it means to that business.\n"
        'Answer with a JSON array of at most 12 objects, best first: {"customer_id": <as given>, "action": <what '
        'to do, one sentence>, "why": <one sentence citing the facts>, "urgency": "now"|"this quarter"|"later", '
        '"pitch": <the pitch text it uses, exactly as given, or null>}. Nothing else.'),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


def check_actions(reply: str, facts: dict) -> list[dict]:
    customers = {row["customer_id"]: row for row in facts["customers"]}
    found = []
    for item in compass.json_array(reply):
        if not isinstance(item, dict) or item.get("customer_id") not in customers or not item.get("action"):
            continue
        row = customers[item["customer_id"]]
        pitch = next((candidate for candidate in row.get("pitches") or [] if candidate["pitch"] == item.get("pitch")), None)
        found.append({"customer_id": row["customer_id"], "customer": row["customer"],
                      "action": str(item["action"])[:300], "why": str(item.get("why") or "")[:400],
                      "urgency": item.get("urgency") if item.get("urgency") in URGENCY else "this quarter",
                      # The value shown is the Solution note's, never the model's.
                      "pitch": pitch["pitch"] if pitch else None, "sized_monthly": (pitch or {}).get("sized_monthly"),
                      "last_month": row.get("last_month")})
    return found[:12]


# -- draft from a pitch -------------------------------------------------------------

def draft_facts(brief_facts: dict, pitch: dict, sizing: dict | None, solution_monthly: float | None = None) -> dict:
    # What the customer already spends in the subscriptions running this solution: without
    # it the size was chosen blind -- ADNOC, at ~$2M a month on GenAI, was drafted "small"
    # (2026-10-23).
    return {"customer": brief_facts.get("customer"), "pitch": pitch.get("pitch"), "because_of": pitch.get("solution"),
            "monthly_today_in_subscriptions_running_it": round(solution_monthly) if solution_monthly else None,
            "play": pitch.get("play"), "subscriptions": pitch.get("subscriptions"),
            "sizing": sizing, "consumption": {key: brief_facts["consumption"].get(key) for key in
                                              ("last_month", "monthly_run_rate_3m", "year_on_year_pct")},
            "commitment": brief_facts.get("commitment"), "existing_pipeline": brief_facts.get("pipeline"),
            "seller_says": brief_facts.get("seller_says"),
            "recent_conversations": (brief_facts.get("vault") or {}).get("recent"),
            "industry": industry_short(brief_facts.get("industry")),
            # A Compass pitch carries the industry use case it serves; a rule's does not.
            "use_case": pitch.get("use_case"), "business_outcome": pitch.get("business_outcome"),
            "business_owner": pitch.get("business_owner")}


def draft_messages(facts: dict) -> list[dict]:
    return [_system(
        "Draft an opportunity and a short email to the customer from this pitch. 'seller_says' is what the seller "
        "told you about the customer: use it.\n"
        'Answer with one JSON object: {"title": <opportunity title, under 80 characters, naming the customer and '
        'the solution>, "summary": <two sentences: the customer need the facts show and what is proposed>, '
        '"size": "small"|"medium"|"large" <which of the sizing fits this customer\'s scale -- compare with what it '
        'already spends in the subscriptions running the solution; when that is far above the large size, choose '
        'large and say in the summary that the sizing is a first phase>, "next_steps": '
        '[<3 short steps>], "email_subject": <subject>, "email_body": <plain text, under 150 words, to the '
        'business owner of the outcome when one is given (else the technical lead), in the language of the '
        'customer\'s industry: the business outcome first, the technical solution second; no figures from inside '
        'Core42 such as quota or pipeline>}. ' + INDUSTRY_RULE + " Nothing else."),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


def check_draft(reply: str, facts: dict) -> dict:
    found = compass.json_object(reply)
    size = found.get("size") if found.get("size") in SIZES else "medium"
    totals = ((facts.get("sizing") or {}).get("totals") or {})
    return {"title": str(found.get("title") or facts.get("pitch") or "")[:120],
            "summary": str(found.get("summary") or "")[:600], "size": size,
            # The value is the Solution note's sizing for the size chosen, never a figure the model wrote.
            "expected_monthly": totals.get(size),
            "next_steps": [str(step)[:200] for step in (found.get("next_steps") or [])[:5]],
            "email_subject": str(found.get("email_subject") or "")[:150],
            "email_body": str(found.get("email_body") or "")[:2000]}


# -- size a solution ---------------------------------------------------------------

def sizing_messages(solution: dict, answers: str, customer_facts: dict | None) -> list[dict]:
    facts = {"solution": solution["name"], "building_blocks": solution["sizing"]["rows"],
             "what_the_seller_knows": answers, "customer": customer_facts}
    return [_system(
        "Size this solution for one customer from its template bill. For each building block choose the size "
        "that fits what the seller knows (small, medium or large) and a quantity factor (1 = as in the bill, e.g. 2 "
        "for twice the users or data), with a short reason. The customer's 'seller_says', when given, is fact.\n"
        'Answer with one JSON object: {"blocks": [{"block": <name exactly as given>, "size": "small"|"medium"|"large", '
        '"factor": <number between 0.25 and 10>, "reason": <short>}], "assumptions": [<what you assumed>], '
        '"questions": [<what to ask to firm it up>]}. Nothing else.'),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


def check_sizing(reply: str, sizing: dict) -> dict:
    """Compass picks a size and a factor per block; the money is the bill's figure times the factor."""
    found = compass.json_object(reply)
    chosen = {item.get("block"): item for item in found.get("blocks") or [] if isinstance(item, dict)}
    rows, total = [], 0.0
    for row in sizing["rows"]:
        pick = chosen.get(row["block"]) or {}
        size = pick.get("size") if pick.get("size") in SIZES else "medium"
        try:
            factor = min(10.0, max(0.25, float(pick.get("factor") or 1)))
        except (TypeError, ValueError):
            factor = 1.0
        base = row.get(size) or 0
        monthly = round(base * factor, 2)
        total += monthly
        rows.append({"block": row["block"], "service": row["service"], "size": size, "factor": factor,
                     "list_monthly": base, "monthly": monthly, "basis": row.get("basis"),
                     "reason": str(pick.get("reason") or "")[:200]})
    return {"rows": rows, "total": round(total, 2),
            "assumptions": [str(item)[:200] for item in (found.get("assumptions") or [])[:6]],
            "questions": [str(item)[:200] for item in (found.get("questions") or [])[:6]]}


# -- ask your data ----------------------------------------------------------------

TOOLS = {
    "customers_using_service": "customers billed for a service, with monthly spend. args: {\"service\": <name>}",
    "customers_running_solution": "customers whose subscriptions run a solution. args: {\"solution\": <name>}",
    "customers_with_but_without": "customers using one service but not another. args: {\"has\": <service>, \"lacks\": <service>}",
    "growth": "customers by growth or decline over three months. args: {\"direction\": \"growing\"|\"declining\"}",
    "macc_status": "every customer's MACC: signed, consumed %, elapsed %, when it runs out. args: {}",
    "customer_summary": "one customer's figures, MACC, solutions and pitches. args: {\"customer\": <name>}",
    "marketplace_buyers": "who buys a Marketplace publisher's or offer's products. args: {\"text\": <publisher or offer words>}",
    "quota": "the seller's quota attainment and each customer above its baseline. args: {}",
    "savings_candidates": "every customer's steady on-demand spend worth committing and its estimated saving. args: {}",
    "hybrid_benefit": "customers billed for Windows Server, SQL Server, RHEL or SUSE licenses Azure Hybrid Benefit could remove. args: {}",
    "commitment_renewals": "customers whose up-front commitments may renew soon (one- or three-year terms). args: {}",
    "customers_by_industry": "customers grouped by industry, with last month's spend; or one industry's customers. args: {\"industry\": <name, or empty for all>}",
    "tag_coverage": "every customer's tag coverage by business dimension (environment, project, application, business unit, owner, cost centre) and how many spellings each key has. args: {}",
}


def plan_messages(question: str, services: list[str], solution_names: list[str]) -> list[dict]:
    tools = "\n".join(f"- {name}: {description}" for name, description in TOOLS.items())
    return [{"role": "system", "content": (
        "You answer a Core42 seller's question about their Azure customers by choosing which reports to read. "
        f"Reports:\n{tools}\n\nKnown services: {', '.join(services[:150])}\nKnown solutions: {', '.join(solution_names)}\n\n"
        'Answer with one JSON object: {"calls": [{"tool": <report name>, "args": {...}}]} -- at most 3 calls, using '
        "service and solution names exactly as known. If no report answers it, {\"calls\": []}. Nothing else.")},
        {"role": "user", "content": question}]


def check_plan(reply: str) -> list[dict]:
    found = compass.json_object(reply)
    return [{"tool": call["tool"], "args": call.get("args") or {}} for call in (found.get("calls") or [])[:3]
            if isinstance(call, dict) and call.get("tool") in TOOLS]


def answer_messages(question: str, results: list[dict]) -> list[dict]:
    return [_system(
        "Answer the seller's question from the report results given -- they are all you know. Name the customers "
        "and figures that answer it; if the results do not answer it, say what they do show. Markdown, at most "
        "180 words; a short list or table where it helps."),
        {"role": "user", "content": f"Question: {question}\n\nReport results:\n" + compass.json_block(results)}]


# -- Marketplace products -----------------------------------------------------------

CATEGORIES = ("Security", "Networking", "Data and databases", "AI and machine learning", "Backup and recovery",
              "Identity", "Productivity and collaboration", "Industry solution", "Developer tools", "Infrastructure",
              "Other")


def marketplace_messages(products: list[dict]) -> list[dict]:
    return [_system(
        "Say what each Azure Marketplace product is, from its publisher, offer and plan names.\n"
        'Answer with a JSON array, one object per product: {"key": <as given>, "category": one of '
        + ", ".join(f'"{name}"' for name in CATEGORIES)
        + ', "what": <one sentence on what it does; say "unclear from the name" when it is>, "compass_alternative": '
        "<true only when it is an AI model or AI inference product that Compass by Core42 could replace>}. "
        "Nothing else."),
        {"role": "user", "content": "Products:\n" + compass.json_block(products)}]


def check_marketplace(reply: str, keys: set[str]) -> dict[str, dict]:
    found = {}
    for item in compass.json_array(reply):
        if isinstance(item, dict) and item.get("key") in keys:
            found[item["key"]] = {"category": item.get("category") if item.get("category") in CATEGORIES else "Other",
                                  "what": str(item.get("what") or "")[:240],
                                  "compass_alternative": bool(item.get("compass_alternative"))}
    return found


# -- what to pitch -------------------------------------------------------------------

def pitch_facts(brief_facts: dict, catalog: list[dict], playbooks: list[dict]) -> dict:
    """What Compass recommends pitches from: the customer as the brief sees it, what the
    rules already pitch, and the catalog it must choose from (with the notes' sizing)."""
    return {
        "customer": brief_facts.get("customer"),
        "consumption": {key: (brief_facts.get("consumption") or {}).get(key) for key in
                        ("last_month", "year_on_year_pct", "monthly_run_rate_3m", "top_services_last_month")},
        "commitment": brief_facts.get("commitment"),
        "running": brief_facts.get("solutions"),
        "already_pitched_by_rules": [item.get("pitch") for item in brief_facts.get("pitches") or []],
        "pipeline": brief_facts.get("pipeline"),
        "seller_says": brief_facts.get("seller_says"),
        "recent_conversations": (brief_facts.get("vault") or {}).get("recent"),
        # The industry note and its use-case notes: what to recommend in the business's language.
        "industry": brief_facts.get("industry") or {"industry": None},
        "catalog": [{"id": pattern["id"], "name": pattern["name"], "play": pattern["play"],
                     "description": pattern.get("description") or "",
                     "sized_monthly": [pattern["sizing"]["totals"][size] for size in SIZES]
                     if pattern.get("sizing") else None} for pattern in catalog],
        "playbooks": [{"name": item["name"], "covers": item.get("solutions") or []} for item in playbooks],
    }


def pitch_messages(facts: dict) -> list[dict]:
    return [_system(
        "Recommend what this seller should pitch to this customer next -- beyond what the rules already pitch "
        "(listed), unless one of those deserves to be first, in which case say why. Weigh what the customer runs "
        "and grows, its MACC position (room to grow consumption, or a commitment running out), its pipeline, its "
        "recent conversations and what the seller told you. Recommend industry use cases, not only technology: "
        "a business outcome for this customer's industry -- from 'industry.use_cases' when one fits, else from its "
        "typical use cases and business drivers -- delivered by a catalog solution. When the industry is not set, "
        "recommend from the facts alone.\n"
        'Answer with a JSON array of at most 5 objects, best first: {"solution_id": <an id from the catalog>, '
        '"use_case": <the industry use case, a few words in the business\'s language>, "business_outcome": <what '
        'it changes for the business, one sentence>, "business_owner": <the role that owns that outcome>, '
        '"pitch": <what to sell, one sentence, naming the situation of the customer>, "why": <one or two sentences '
        'citing the facts and the industry>, "playbook": <a playbook name exactly as given, or null>, "confidence": '
        '"high"|"medium"|"low"}. Only solutions in the catalog. ' + INDUSTRY_RULE + " Nothing else."),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


def check_pitches(reply: str, facts: dict) -> list[dict]:
    """Recommendations about catalog solutions only; the sizing is the note's."""
    catalog = {item["id"]: item for item in facts["catalog"]}
    playbooks = {item["name"] for item in facts["playbooks"]}
    use_case_notes = {item["use_case"].lower(): item["note"]
                      for item in (facts.get("industry") or {}).get("use_cases") or []}
    found, seen = [], set()
    for item in compass.json_array(reply):
        if not isinstance(item, dict) or item.get("solution_id") not in catalog or not str(item.get("pitch") or "").strip():
            continue
        pitch = str(item["pitch"]).strip()[:300]
        if pitch in seen:
            continue
        seen.add(pitch)
        solution = catalog[item["solution_id"]]
        use_case = str(item.get("use_case") or "").strip()[:120] or None
        found.append({"pitch": pitch, "use_case": use_case,
                      "use_case_note": use_case_notes.get((use_case or "").lower()),
                      "business_outcome": str(item.get("business_outcome") or "")[:300] or None,
                      "business_owner": str(item.get("business_owner") or "")[:80] or None,
                      "solution_id": solution["id"], "solution": solution["name"],
                      "play": solution["play"], "why": str(item.get("why") or "")[:500],
                      "playbook": item.get("playbook") if item.get("playbook") in playbooks else None,
                      "confidence": item.get("confidence") if item.get("confidence") in ("high", "medium", "low") else "medium",
                      "sized_monthly": solution["sized_monthly"]})
    return found[:5]


# -- FinOps ----------------------------------------------------------------------------

FINOPS_MOVES = ("reserve", "savings_plan", "hybrid_benefit", "keep_on_demand", "investigate")
RISK = ("low", "medium", "high")


def finops_facts(finops: dict, brief_facts: dict | None, customer_view: bool = False,
                 industry: dict | None = None) -> dict:
    """What Compass reads for the savings plan: the FinOps findings as computed, and --
    for the seller, never the customer -- the MACC, the pitches and what the seller said."""
    candidates = [{"meter": item["meter"], "family": item["family"], "monthly_on_demand": item["monthly_on_demand"],
                   "variation_pct": item["variation_pct"], "lowest_month": item["lowest_month"],
                   "savings_monthly_by_option": item.get("savings"), "not_priced": item.get("not_priced")}
                  for item in (finops.get("candidates") or [])[:15]]
    facts = {
        "customer": (finops.get("customer") or {}).get("name"),
        "coverage": {"latest": (finops.get("coverage") or {}).get("latest"),
                     "by_month": ((finops.get("coverage") or {}).get("months") or [])[-6:]},
        "candidates": candidates,
        "savings_options": {"ri_1y": "1-year reservation", "ri_3y": "3-year reservation",
                            "sp_1y": "1-year savings plan", "sp_3y": "3-year savings plan"},
        "bought_up_front": finops.get("renewals"),
        "hybrid_benefit": finops.get("hybrid_benefit"),
        "worth_a_look": (finops.get("waste") or [])[:10],
        "fastest_growing_services": ((finops.get("growth") or {}).get("services") or [])[:6],
        "budget": finops.get("budget"),
        # Read on real bills (2026-10-24): both were mistaken for spend to act on.
        "how_to_read": [*brief.HOW_TO_READ,
                        "Azure Hybrid Benefit can remove only the hybrid_benefit amounts, never the rest of the licenses."],
        # The customer's own industry: fine for the customer's report as for the seller's plan.
        "industry": industry_short(industry),
    }
    if not customer_view and brief_facts:
        facts.update(commitment=brief_facts.get("commitment"), pitches=brief_facts.get("pitches"),
                     running=brief_facts.get("solutions"), seller_says=brief_facts.get("seller_says"))
    return facts


def finops_plan_messages(facts: dict) -> list[dict]:
    return [_system(
        "Turn this customer's FinOps findings into a savings plan for the seller. For each steady candidate decide: "
        "reserve (a family that will keep running), a savings plan (spread across families or likely to change "
        "size), or keep on demand (growing fast, new, a dev/test subscription, shrinking -- say why). Use Azure Hybrid "
        "Benefit where license meters are billed. Raise what is worth a look as questions, not as waste. Then the "
        "reinvestment story: a Core42 seller is paid on consumption, so frame savings as money to put into what the "
        "customer is building or should pitch, keeping MACC consumption, never as spend cut. Say where the budget "
        "stands in one sentence. Tell the reinvestment story in the customer's industry: the business drivers "
        "and use cases the savings could fund. " + INDUSTRY_RULE + "\n"
        'Answer with one JSON object: {"summary": <3-4 sentences>, "moves": [{"kind": "reserve"|"savings_plan"|'
        '"hybrid_benefit"|"keep_on_demand"|"investigate", "ref": <the candidate meter, the hybrid benefit product, or '
        'the subscription, exactly as given>, "option": "ri_1y"|"ri_3y"|"sp_1y"|"sp_3y"|null, "why": <one sentence>, '
        '"risk": "low"|"medium"|"high", "risk_reason": <short>}], "reinvest": <2-3 sentences>, "questions": [<up to 4 '
        "for the customer's engineers>]}. At most 10 moves, largest first. Nothing else."),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


def check_finops_plan(reply: str, facts: dict) -> dict:
    """Moves about things in the facts only; each saving is the plugin's figure."""
    found = compass.json_object(reply)
    candidates = {item["meter"]: item for item in facts["candidates"]}
    hybrid = {item["product"]: item for item in facts.get("hybrid_benefit") or []}
    looks = {item["subscription"]: item for item in facts.get("worth_a_look") or []}
    moves = []
    for move in found.get("moves") or []:
        if not isinstance(move, dict) or move.get("kind") not in FINOPS_MOVES:
            continue
        ref, kind, saving, option = move.get("ref"), move["kind"], None, None
        if kind in ("reserve", "savings_plan", "keep_on_demand"):
            candidate = candidates.get(ref)
            if not candidate:
                continue
            options = candidate.get("savings_monthly_by_option") or {}
            option = move.get("option") if move.get("option") in options else None
            if kind == "reserve" and not (option or "").startswith("ri_"):
                option = "ri_3y" if "ri_3y" in options else None
            if kind == "savings_plan" and not (option or "").startswith("sp_"):
                option = "sp_1y" if "sp_1y" in options else None
            saving = options.get(option) if option and kind != "keep_on_demand" else None
            monthly = candidate["monthly_on_demand"]
        elif kind == "hybrid_benefit":
            if ref not in hybrid:
                continue
            saving, monthly = hybrid[ref]["monthly"], hybrid[ref]["monthly"]
        else:
            if ref not in looks and ref not in candidates:
                continue
            monthly = (looks.get(ref) or {}).get("monthly_at_stake") or (candidates.get(ref) or {}).get("monthly_on_demand")
        subject = "license" if kind == "hybrid_benefit" else "subscription" if ref in looks and ref not in candidates else "meter"
        moves.append({"kind": kind, "ref": ref, "subject": subject, "option": option, "monthly": monthly,
                      # "up to" for hybrid benefit: only when the customer holds the licenses.
                      "saving_monthly": saving, "why": str(move.get("why") or "")[:300],
                      "risk": move.get("risk") if move.get("risk") in RISK else "medium",
                      "risk_reason": str(move.get("risk_reason") or "")[:200]})
    return {"summary": str(found.get("summary") or "")[:900], "moves": moves[:10],
            "reinvest": str(found.get("reinvest") or "")[:700],
            "questions": [str(item)[:240] for item in (found.get("questions") or [])[:4]]}


def finops_report_messages(facts: dict) -> list[dict]:
    return [_system(
        "Write a short savings report for the CUSTOMER's IT and finance leads, from these findings of their own "
        "Azure bill. Nothing about the seller, quotas, pipeline, MACC targets or pitches. Plain, specific, helpful: "
        "commitment coverage today; the steady usage worth committing and the estimated monthly saving per option "
        "(figures exactly as given); Azure Hybrid Benefit where license meters are billed, if they hold the "
        "licenses; what is worth checking (as questions); where they stand on budget. Markdown with headings "
        "'Where you stand', 'Commit to save', 'Licenses you may already own', 'Worth checking', 'Next steps'; under "
        "350 words. A section with nothing to say is left out. Where the industry is given, write in its terms "
        "(what the savings could fund for that business). " + INDUSTRY_RULE),
        {"role": "user", "content": "Findings:\n" + compass.json_block(facts)}]


# -- tagging --------------------------------------------------------------------------

TAGGING_MOVES = ("adopt_key", "standardize_key", "normalize_values", "inherit", "enforce_policy", "backfill",
                 "allocate_untagged")
EFFORT = ("low", "medium", "high")


def tagging_facts(report: dict, brief_facts: dict | None, customer_view: bool = False,
                  industry: dict | None = None) -> dict:
    """What Compass reads for tagging: the gaps as computed, and -- for the seller only --
    what the customer runs, the pitches and what the seller said."""
    gaps = report.get("gaps") or {}
    facts = {
        "customer": (report.get("customer") or {}).get("name"),
        "currency": report.get("currency"),
        "standard_dimensions": gaps.get("standard"),
        "coverage_target_pct": gaps.get("coverage_target_pct"),
        "tag_keys_in_use": gaps.get("tag_keys"),
        "dimensions": gaps.get("dimensions"),
        "not_used_at_all": gaps.get("missing"),
        "environment_in_subscription_names": gaps.get("environment_in_subscription_names"),
        "enrollments_without_any_tag": gaps.get("enrollments_without_tags"),
        "coverage_is_of": "spend tags can be on: commitment purchases and third-party software billed as VM licenses are left out",
        "industry": industry_short(industry),
    }
    if not customer_view and brief_facts:
        facts.update(running=brief_facts.get("solutions"), pitches=brief_facts.get("pitches"),
                     seller_says=brief_facts.get("seller_says"))
    return facts


def tagging_plan_messages(facts: dict) -> list[dict]:
    return [_system(
        "Turn this customer's tagging gaps into a tagging plan for the seller. Tagging is what makes showback, "
        "chargeback, FinOps and budgets per team possible -- the seller's way into a governance conversation. "
        "For each gap choose a move: adopt_key (a standard dimension not used), standardize_key (one spelling "
        "instead of several), normalize_values (one value instead of prd/prod/PROD), inherit (tag inheritance from "
        "the subscription or resource group -- use it where subscription names already say the environment), "
        "enforce_policy (Azure Policy: require on new resources, then Modify to add missing tags), backfill (tag "
        "what exists), allocate_untagged (split untagged shared cost by a rule). Order by what moves coverage most "
        "for least effort. Then one or two sentences on what the seller can offer (a governance or landing-zone "
        "engagement, Cost Management views per team), and questions for the customer's cloud team. In a "
        "regulated industry, say which tags its regulation calls for (data classification, residency, the "
        "regulated workload) from 'industry.regulation'. " + INDUSTRY_RULE + "\n"
        'Answer with one JSON object: {"summary": <3 sentences>, "moves": [{"kind": <one of the moves>, '
        '"dimension": <a standard dimension, exactly as given>, "detail": <what exactly: keys, values, scope>, '
        '"why": <one sentence>, "effort": "low"|"medium"|"high"}], "offer": <1-2 sentences>, "questions": [<up to 4>]}. '
        "At most 8 moves. Nothing else."),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


def check_tagging_plan(reply: str, facts: dict) -> dict:
    """Moves about the standard dimensions only; each carries the plugin's coverage and
    untagged spend, never the model's."""
    found = compass.json_object(reply)
    by_dimension = {item["dimension"]: item for item in facts.get("dimensions") or []}
    moves = []
    for move in found.get("moves") or []:
        if not isinstance(move, dict) or move.get("kind") not in TAGGING_MOVES:
            continue
        dimension = by_dimension.get(move.get("dimension"))
        if not dimension:
            continue
        moves.append({"kind": move["kind"], "dimension": dimension["dimension"],
                      "coverage_pct": dimension.get("coverage_pct"),
                      "untagged_last_month": dimension.get("untagged_last_month"),
                      "detail": str(move.get("detail") or "")[:300], "why": str(move.get("why") or "")[:300],
                      "effort": move.get("effort") if move.get("effort") in EFFORT else "medium"})
    return {"summary": str(found.get("summary") or "")[:900], "moves": moves[:8],
            "offer": str(found.get("offer") or "")[:500],
            "questions": [str(item)[:240] for item in (found.get("questions") or [])[:4]]}


def tagging_guide_messages(facts: dict) -> list[dict]:
    return [_system(
        "Write tagging guidance for the CUSTOMER's cloud and finance teams, from these findings of their own Azure "
        "bill. Nothing about the seller, quotas, pipeline or pitches. Practical and specific to them: figures "
        "exactly as given, their own key spellings and values named. Markdown with headings 'Where you stand' "
        "(coverage per dimension, what is not used, the spellings and values that drift), 'A tagging standard' (a "
        "table: tag key -- one spelling each, allowed values, required or optional, who owns it; keep keys they "
        "already use where one is clearly dominant), 'Close the gaps' (inheritance from subscriptions or resource "
        "groups where names already say the environment, backfilling, folding values), 'Enforce it' (Azure Policy: "
        "require tags on new resource groups and resources, inherit from the subscription or resource group with "
        "Modify, audit first then deny), 'Next steps'. Under 450 words. Where the industry's regulation calls for "
        "tags (data classification, residency), include them in the standard and say which rule they serve. "
        + INDUSTRY_RULE),
        {"role": "user", "content": "Findings:\n" + compass.json_block(facts)}]


# -- an industry use case, in detail ---------------------------------------------------

def use_case_facts(brief_facts: dict, pitch: dict, solution: dict | None) -> dict:
    """What Compass drafts a use case from: the industry note, the Solution note the pitch
    is built on (its pattern, architecture and sizing), and -- for the customer part only --
    what the customer runs and what the seller said."""
    found = brief_facts.get("industry") or {}
    return {
        "use_case": pitch.get("use_case") or pitch.get("pitch"), "pitch": pitch.get("pitch"),
        "business_outcome": pitch.get("business_outcome"), "business_owner": pitch.get("business_owner"),
        "why_compass_recommended_it": pitch.get("why"),
        "industry": {key: found.get(key) for key in ("industry", "part_of", "what_it_is", "business_drivers",
                                                    "typical_use_cases", "regulation", "our_positioning")
                     if found.get(key)},
        "solution": {"name": (solution or {}).get("name"), "note": (solution or {}).get("note"),
                     "what_it_is": (solution or {}).get("description"),
                     "architecture": ((solution or {}).get("architecture") or "")[:1500] or None,
                     "sized_monthly_small_medium_large": [solution["sizing"]["totals"][size] for size in SIZES]
                     if (solution or {}).get("sizing") else None},
        "customer": {"name": brief_facts.get("customer"), "running": brief_facts.get("solutions"),
                     "top_services_last_month": (brief_facts.get("consumption") or {}).get("top_services_last_month"),
                     "commitment": brief_facts.get("commitment"), "seller_says": brief_facts.get("seller_says")},
    }


def use_case_messages(facts: dict) -> list[dict]:
    return [_system(
        "Write this industry use case out in detail, in two parts. 'note' is about the INDUSTRY, reusable for any "
        "customer in it: never name this customer, its figures or its people there. 'for_this_customer' is why "
        "and how it lands at this customer, from its facts. Business language first -- the outcome, who owns it, "
        "why now (the industry's drivers and regulation) -- then how the solution delivers it, from the solution's "
        "architecture. KPIs are the measures the business owner would track; give no numbers the facts do not "
        "have.\n"
        'Answer with one JSON object: {"note": {"name": <the use case, a few words>, "outcome": <one sentence>, '
        '"buyer": <the role that owns it>, "summary": <2-3 sentences>, "business_outcome": <a short paragraph>, '
        '"who_owns_it": <the owner, who else decides and who uses it>, "why_now": <drivers and regulation, '
        'named>, "how_it_is_delivered": <the solution\'s building blocks and flow, a short paragraph or bullets>, '
        '"value_and_kpis": <bullets>, "discovery_questions": [<4-6 questions>], "core42_angle": <in-country, '
        'Compass by Core42, Azure: where it matters here>}, "for_this_customer": {"why_them": <2-4 sentences '
        'citing its facts>, "first_step": <one concrete next step>, "questions": [<2-3 questions for this '
        'customer>]}}. Markdown is allowed inside the strings. ' + INDUSTRY_RULE + " Nothing else."),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


def check_use_case(reply: str, facts: dict) -> dict:
    found = compass.json_object(reply)
    note = found.get("note") if isinstance(found.get("note"), dict) else {}
    mine = found.get("for_this_customer") if isinstance(found.get("for_this_customer"), dict) else {}

    def text(value, limit: int) -> str:
        return str(value or "").strip()[:limit]

    return {
        "note": {"name": text(note.get("name") or facts.get("use_case"), 120),
                 "outcome": text(note.get("outcome"), 300), "buyer": text(note.get("buyer"), 120),
                 **{key: text(note.get(key), 2500) for key in ("summary", "business_outcome", "who_owns_it", "why_now",
                                                                "how_it_is_delivered", "value_and_kpis", "core42_angle")},
                 "discovery_questions": [text(item, 300) for item in (note.get("discovery_questions") or [])[:6] if item]},
        "for_this_customer": {"why_them": text(mine.get("why_them"), 1500), "first_step": text(mine.get("first_step"), 400),
                              "questions": [text(item, 300) for item in (mine.get("questions") or [])[:3] if item]},
    }
