"""Where a customer stands, as the seller knows it (operator, 2026-10-24).

Worth pinning: only the six fields are kept, a field left empty is not handed to a
prompt, clearing every field forgets the customer, and Compass's draft is checked to the
fields -- it is a draft, never saved by itself.
"""
from __future__ import annotations

import json
from datetime import date

from backend import advisor, customer_profile


def profile():
    state: dict = {}
    return customer_profile.CustomerProfile(lambda: state, lambda new: (state.clear(), state.update(new)),
                                            lambda: date(2026, 10, 24)), state


def test_only_the_fields_are_kept_and_only_filled_ones_are_handed():
    found, _ = profile()

    saved = found.save("fab", {"data_today": "  Data in   three warehouses ", "colour": "blue", "priorities": ""})

    assert saved["fields"]["data_today"] == "Data in three warehouses" and "colour" not in saved["fields"]
    assert saved["updated"] == "2026-10-24"
    assert found.handed("fab") == {"Their data today": "Data in three warehouses"}


def test_clearing_every_field_forgets_the_customer():
    found, state = profile()
    found.save("fab", {"ai_readiness": "pilots"})

    found.save("fab", {})

    assert "fab" not in state and found.handed("fab") is None


def test_compass_drafts_only_the_fields():
    reply = json.dumps({"digital_maturity": "Cloud-first.", "invented": "x"})

    draft = advisor.check_context(reply, customer_profile.KEYS)

    assert set(draft) == set(customer_profile.KEYS) and draft["digital_maturity"] == "Cloud-first."
    assert draft["constraints"] == ""


def test_pitches_and_drafts_are_handed_the_context():
    brief_facts = {"customer": "FAB", "consumption": {}, "customer_context": {"AI readiness": "pilots only"}}

    assert advisor.pitch_facts(brief_facts, [], [])["customer_context"] == {"AI readiness": "pilots only"}
    assert advisor.draft_facts(brief_facts, {"pitch": "p"}, None)["customer_context"] == {"AI readiness": "pilots only"}
    assert advisor.use_case_facts(brief_facts, {"pitch": "p"}, None)["customer"]["customer_context"] == {"AI readiness": "pilots only"}
