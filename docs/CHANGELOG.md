# Project updates

## Version 2: a calmer employee workspace

- Sage, cream and lavender workspace, serif welcome area, PTO summary, and a question-centered layout distinct from the sales and analytics apps.
- Prominent, expandable citations include handbook title, version and the exact supporting passage. Only sources actually cited are returned with a generated answer.
- A visible boundary diagram separates read-only answers from ledger access, reservations and human review.
- Retrieval and routing now live in separate pure modules. The API and benchmark use the same routing controls. Known unsupported handbook subjects escalate rather than matching broad words such as “company” or “PTO.”
- **22 automated tests passed** on Python 3.13, including existing concurrency/access tests and end-to-end benchmark/citation checks. Ruff lint/format and JavaScript syntax checks pass; browser checks covered citations, reservations, reviewer approval, and desktop/phone layouts.
