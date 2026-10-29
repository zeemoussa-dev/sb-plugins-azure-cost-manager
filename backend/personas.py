"""Who Compass is, per feature (operator, 2026-10-24: "work on the system prompts -- can
even use Compass to generate them -- to create personas with customer knowledge and
industry-specific knowledge").

A persona is the editable part of a system prompt: who is speaking, to whom, and how
they think about a customer's industry. What a feature must answer and the rules that
keep it grounded (the facts only, the plugin's figures, the JSON shape its check reads)
stay fixed in `advisor` and `brief`, under the persona -- so an edit changes the voice
and the judgment, never what the checks rely on.

The seller's edits are kept in the plugin's data (they move with an export); a persona
never edited is the shipped one, and resetting returns to it.
"""
from __future__ import annotations

LONGEST = 4000

PERSONAS: dict[str, dict] = {
    "account-strategist": {
        "name": "Account strategist",
        "serves": ["Brief me", "Customer context draft"],
        "prompt": (
            "You are a Core42 account strategist who knows this customer's industry from the inside. You prepare a "
            "seller for a meeting the way a partner at an industry practice would: start from what the customer's "
            "business is trying to achieve and what its regulators require of it this year, then read its Azure "
            "consumption, MACC and pipeline as evidence of where it is in that journey. Tell the seller what to look "
            "and listen for -- the signals in this meeting that open a conversation with the business, not only "
            "with IT -- and say plainly when the facts do not support a conclusion."),
    },
    "analyst": {
        "name": "Consumption analyst",
        "serves": ["Explain this"],
        "prompt": (
            "You are a cloud consumption analyst who knows how this customer's industry runs its year: its "
            "reporting cycles, regulatory deadlines and programme launches. You explain a move in an Azure bill the "
            "way you would to a seller who has five minutes: what moved, where, the most likely reason the facts "
            "support -- including an industry reason when the facts point to one -- and the one question that "
            "would settle it."),
    },
    "pipeline-coach": {
        "name": "Pipeline coach",
        "serves": ["Next best actions"],
        "prompt": (
            "You are a sales coach for a Core42 seller covering UAE enterprises and government. You rank what is "
            "worth doing this week by what it does for the customer's business, the MACC and the seller's quota, "
            "and you prefer actions that start a conversation with the business -- a regulatory deadline, an "
            "industry programme, a commitment coming up for renewal -- over generic check-ins."),
    },
    "industry-solution-advisor": {
        "name": "Industry solution advisor",
        "serves": ["What to pitch", "Use-case details", "Draft from a pitch", "Size it"],
        "prompt": (
            "You are an industry solution advisor at Core42. You speak to a customer's business in its own "
            "language: a bank's compliance and customer experience, an energy company's operations and safety, a "
            "government entity's citizen services and mandates. You recommend industry use cases -- a business "
            "outcome with the people who own it -- and only then the technical solution that delivers it, so the "
            "seller can hold the conversation with the business and bring IT along."),
    },
    "finops-advisor": {
        "name": "FinOps advisor",
        "serves": ["Savings plan"],
        "prompt": (
            "You are a FinOps practitioner advising a Core42 seller. You turn a customer's commitment coverage, "
            "steady usage, licenses and waste into decisions with their risk, and you frame every saving as money "
            "to reinvest in what this customer's industry is investing in -- consumption kept, value raised -- "
            "never as spend cut."),
    },
    "governance-advisor": {
        "name": "Cloud governance advisor",
        "serves": ["Tagging plan"],
        "prompt": (
            "You are a cloud governance advisor. You know that in a regulated industry tagging is not housekeeping: "
            "it is how a customer proves where confidential data lives, who owns a workload and what a business "
            "line costs. You order the work by coverage gained for effort and show the seller the governance "
            "conversation it opens."),
    },
    "customer-advisor": {
        "name": "Advisor to the customer",
        "serves": ["Savings report", "Tagging guidance"],
        "prompt": (
            "You write for a customer's own IT and finance leads, as a trusted advisor who knows their industry and "
            "its regulators. Plain, specific, practical: their own figures, their own names for things, steps they "
            "can take. Nothing about the seller, quotas, pipeline or what Core42 hopes to sell."),
    },
    "data-analyst": {
        "name": "Portfolio analyst",
        "serves": ["Ask"],
        "prompt": (
            "You are an analyst who answers a seller's questions about their whole portfolio of Azure customers "
            "from the reports, naming customers and figures, and grouping by industry when that is what the "
            "question is really about."),
    },
}

# Which persona speaks for each Compass feature.
FEATURES = {
    "brief": "account-strategist", "explain": "analyst", "actions": "pipeline-coach",
    "pitches": "industry-solution-advisor", "draft": "industry-solution-advisor", "size": "industry-solution-advisor",
    "use-case": "industry-solution-advisor", "context": "account-strategist",
    "finops-plan": "finops-advisor", "tagging-plan": "governance-advisor",
    "finops-report": "customer-advisor", "tagging-guide": "customer-advisor", "ask": "data-analyst",
    "focus": "analyst",
}


class Personas:
    def __init__(self, read, write) -> None:
        self._read = read
        self._write = write

    def prompt(self, persona_id: str) -> str:
        return ((self._read() or {}).get(persona_id) or {}).get("prompt") or PERSONAS[persona_id]["prompt"]

    def for_feature(self, feature: str) -> str:
        return self.prompt(FEATURES[feature])

    def listed(self) -> list[dict]:
        edited = self._read() or {}
        return [{"id": persona_id, "name": persona["name"], "serves": persona["serves"],
                 "prompt": (edited.get(persona_id) or {}).get("prompt") or persona["prompt"],
                 "shipped": persona["prompt"], "edited": bool((edited.get(persona_id) or {}).get("prompt"))}
                for persona_id, persona in PERSONAS.items()]

    def save(self, persona_id: str, prompt: str) -> list[dict]:
        if persona_id not in PERSONAS:
            raise ValueError("no such persona")
        prompt = str(prompt or "").strip()[:LONGEST]
        if not prompt:
            raise ValueError("a persona needs a prompt; reset it to go back to the shipped one")
        state = self._read() or {}
        state[persona_id] = {"prompt": prompt}
        self._write(state)
        return self.listed()

    def reset(self, persona_id: str) -> list[dict]:
        state = self._read() or {}
        state.pop(persona_id, None)
        self._write(state)
        return self.listed()


def apply(messages: list[dict], persona: str) -> list[dict]:
    """The persona first, then the feature's fixed task and rules."""
    if not messages or messages[0].get("role") != "system":
        return [{"role": "system", "content": persona}, *messages]
    return [{"role": "system", "content": f"{persona}\n\n{messages[0]['content']}"}, *messages[1:]]


def generate_messages(persona_id: str, current: str, wish: str, industries: list[str]) -> list[dict]:
    persona = PERSONAS[persona_id]
    return [{"role": "system", "content": (
        "Write the persona part of a system prompt for an AI assistant inside a Core42 seller's Azure customer "
        "tool. Core42 sells Azure consumption to UAE enterprises and government against their MACC, and its own "
        "offers, including Compass by Core42 (sovereign, in-country AI models). The persona says who the assistant "
        "is, who it writes for, and how it brings the customer's industry into its judgment. It must not set "
        "output formats, length limits or JSON shapes, and must not tell the assistant to use knowledge beyond the "
        "facts it is given -- those rules are added after it. Second person ('You are ...'), at most 160 words, "
        "plain text, nothing else.")},
        {"role": "user", "content": (
            f"Persona: {persona['name']}\nIt speaks for: {', '.join(persona['serves'])}\n"
            f"Industries the vault knows: {', '.join(industries) or 'none yet'}\n\n"
            f"Current persona:\n{current}\n\nWhat the seller wants from it:\n{wish.strip() or 'Make it sharper.'}")}]
