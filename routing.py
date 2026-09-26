"""Pure routing controls. These run before retrieval or generation."""

import re


def route_question(question, who="alex", people=("alex", "jordan", "sam")):
    q = question.lower()
    # Records never enter generation. Unknown personal requests fail closed below.
    personal_other = any(
        re.search(r"\b" + name + r"\b", q) for name in people if name != who
    ) or any(
        x in q
        for x in [
            "coworker",
            "colleague",
            "everyone",
            "all employees",
            "other employee",
        ]
    )
    sensitive = any(
        x in q
        for x in [
            "diagnos",
            "harass",
            "discrimin",
            "fire ",
            "firing",
            "terminate",
            "salary",
            "compensation",
            "pay dispute",
            "medical",
            "accommodation",
            "eligible",
            "eligibility",
        ]
    )
    ambiguous = any(
        term in q
        for term in [
            "exception",
            "unpaid",
            "not sure",
            "unsure",
            "can i take",
            "am i allowed",
            "may i take",
            "salaries",
        ]
    )
    if personal_other or sensitive or ambiguous:
        return "escalate"
    if any(x in q for x in ["balance", "how much pto", "pto left", "remaining pto"]):
        return "ledger"
    if any(
        x in q for x in ["request time off", "take time off", "book pto", "request pto", "vacation"]
    ):
        return "request"
    # Handbook has no policy for these subjects; keyword overlap is not support.
    if any(
        x in q
        for x in [
            "carry over",
            "carryover",
            "rollover",
            "roll over",
            "dental",
            "retirement",
            "401k",
            "401(k)",
            "bereavement",
            "pet insurance",
            "parking",
            "lunch menu",
        ]
    ):
        return "unsupported"
    return "retrieve"
