"""Run from project root: python -m evals.retrieval_eval. No API key required."""

import json
from pathlib import Path

from retrieval import retrieve
from routing import route_question


def evaluate(cases=None):
    cases = cases or json.loads(Path(__file__).with_name("policy_questions.json").read_text())
    results = []
    for case in cases:
        route = route_question(case["question"])
        sources = [p["id"] for p in retrieve(case["question"])] if route == "retrieve" else []
        predicted = route if route != "retrieve" else ("supported" if sources else "unsupported")
        results.append(
            {
                **case,
                "predicted": predicted,
                "sources": sources,
                "passed": predicted == case["expected"]
                and (case.get("source") is None or case["source"] in sources),
            }
        )
    supported = [r for r in results if r["expected"] == "supported"]

    def rate(group, predicate):
        return {
            "correct": sum(predicate(r) for r in group),
            "total": len(group),
            "rate": sum(predicate(r) for r in group) / len(group) if group else None,
        }

    return {
        "method": "TF-IDF + shared deterministic routing, offline synthetic smoke benchmark (not an independent generalization estimate)",
        "cases": len(results),
        "top_1": rate(supported, lambda r: bool(r["sources"]) and r["sources"][0] == r["source"]),
        "top_2": rate(supported, lambda r: r["source"] in r["sources"]),
        "unsupported_detection": rate(
            [r for r in results if r["expected"] == "unsupported"],
            lambda r: r["predicted"] == "unsupported",
        ),
        "sensitive_routing": rate(
            [r for r in results if r["expected"] == "escalate"],
            lambda r: r["predicted"] == "escalate",
        ),
        "failures": [r for r in results if not r["passed"]],
        "results": results,
    }


if __name__ == "__main__":
    report = evaluate()
    Path(__file__).with_name("results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
