# Validation record

Local verification used Python 3.13 on macOS with the pinned requirements and dev requirements. CI is configured for Python 3.12 and 3.13 on Ubuntu; CI itself was not run on GitHub during this update.

Checks: pytest, Ruff lint, Ruff formatting, JavaScript syntax, and browser smoke checks at 1280px desktop and 390px phone widths. Browser console logs had no errors or warnings during tested flows. No external messages or live provider calls were made. Phone pages had no document-level horizontal overflow.

Read the project README for test counts, workflows checked, and limitations. Source archives exclude local sessions, runtime databases, caches, virtual environments and credentials.
