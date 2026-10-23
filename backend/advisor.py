"""The seller's Compass features beyond the brief and placements (operator,
2026-10-23): explaining a move, the next best actions across customers, drafting
from a pitch, sizing a solution, answering a question from the reports, and
saying what a Marketplace product is.

Pure: facts in, prompt out, Compass's answer checked. Every figure a seller sees
is one the plugin computed -- a model's number is never shown as a fact.
"""
from __future__ import annotations

from . import compass

RULES = (
    "Use ONLY the facts given. Never invent a number, a date, a person, a product or an event; quote figures as "
    "given (you may round them, e.g. $1.2M). When the facts do not say, say so. Write for a Core42 seller who sells "
    "Azure consumption against the customer's MACC and Core42's own offers, including Compass by Core42 (sovereign, "
    "in-country AI models). Be specific and brief."
)
SIZES = ("small", "medium", "large")
URGENCY = ("now", "this quarter", "later")


def _system(task: str) -> dict:
    return {"role": "system", "content": f"{task}\n\nRules:\n- {RULES}"}


# -- explain a move ----------------------------------------------------------------

def explain_facts(drill: dict, current_month: str | None = None) -> dict:
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
    }.items() if value not in (None, [], {})}


def explain_messages(facts: dict) -> list[dict]:
    return [_system(
        "Explain to the seller what this item of a customer's Azure bill is doing: what moved and when, where it "
        "moved (which of the parts it is made of), the most likely reason the facts support, and the one question "
        "to ask the customer. Monthly figures are monthly averages of the last closed months unless a month is "
        "named; 'last_12' is a twelve-month total. A month marked partial is still being billed: never read it as "
        "a fall. Markdown, at most 120 words, no headings: two or three short "
        "paragraphs, the question in bold at the end."),
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts)}]


# -- next best actions -------------------------------------------------------------

def action_facts(portfolio: list[dict], growth: dict[str, dict], quota: dict, pitches: dict[str, list[dict]],
                 pipeline: dict[str, dict], limit: int = 30) -> dict:
    """One line per top-level customer, the largest last month first, and the seller's quota."""
    rows = []
    for row in sorted((item for item in portfolio if not item.get("parent")),
                      key=lambda item: -((item.get("last_month") or {}).get("actual") or 0))[:limit]:
        burn = row.get("burn") or {}
        moved = growth.get(row["id"]) or {}
        above = next((item for item in quota.get("customers") or [] if item["id"] == row["id"]), {})
        rows.append({key: value for key, value in {
            "customer_id": row["id"], "customer": row["name"],
            "last_month": round((row.get("last_month") or {}).get("actual") or 0),
            "change_3m_pct": moved.get("change_3m_pct"), "change_12m_pct": moved.get("change_12m_pct"),
            "signals": [signal.get("text") for signal in moved.get("signals") or []][:3],
            "macc": {"signed": row.get("signed"), "consumed_pct": burn.get("consumed_pct"),
                     "elapsed_pct": burn.get("elapsed_pct"), "runs_out": burn.get("projected_exhaustion"),
                     "shortfall_at_end": burn.get("projected_shortfall"), "ends": burn.get("end")} if burn else None,
            "above_baseline_projected": round(above["above_projected"]) if above.get("above_projected") is not None else None,
            "pitches": pitches.get(row["id"]) or [],
            "open_pipeline": pipeline.get(row["id"]),
        }.items() if value not in (None, [], {})})
    return {"quota": {key: quota.get(key) for key in ("above_projected", "gap_to_quota", "projected_pct")},
            "customers": rows}


def action_messages(facts: dict) -> list[dict]:
    return [_system(
        "Rank the seller's next best actions across these customers -- the ones most worth doing this week for "
        "the customer, the MACC and the seller's quota. Consider: a MACC running out before its end (renewal or "
        "top-up), a MACC heading for a shortfall (consumption to grow), sharp growth or decline, pitches with "
        "their sizing, and thin pipeline.\n"
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
            "recent_conversations": (brief_facts.get("vault") or {}).get("recent")}


def draft_messages(facts: dict) -> list[dict]:
    return [_system(
        "Draft an opportunity and a short email to the customer from this pitch.\n"
        'Answer with one JSON object: {"title": <opportunity title, under 80 characters, naming the customer and '
        'the solution>, "summary": <two sentences: the customer need the facts show and what is proposed>, '
        '"size": "small"|"medium"|"large" <which of the sizing fits this customer\'s scale -- compare with what it '
        'already spends in the subscriptions running the solution; when that is far above the large size, choose '
        'large and say in the summary that the sizing is a first phase>, "next_steps": '
        '[<3 short steps>], "email_subject": <subject>, "email_body": <plain text, under 150 words, to the '
        'customer\'s technical lead, no figures from inside Core42 such as quota or pipeline>}. Nothing else.'),
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
        "for twice the users or data), with a short reason.\n"
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
