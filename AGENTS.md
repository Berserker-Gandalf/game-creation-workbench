# Repository instructions

## Think before coding

State assumptions and tradeoffs. Inspect the existing implementation and tests before changing behavior. Ask when a material requirement cannot be inferred.

## Keep changes simple and surgical

Implement only the requested behavior, match existing style, and avoid adjacent cleanup. Remove unused code introduced by your changes. Every changed line should trace to the task.

## Verify concrete goals

State a brief plan with checks for multi-step work. Run `python -X utf8 -m pytest -q` and `npm run build` for relevant source changes. Run `python scripts/check_release.py` before preparing a public release. Distinguish simulated API tests, real account requests, engine compilation, and engine runtime verification.

## Protect local work

Never commit `.workbench/`, `.dev/`, credentials, API keys, account tokens, logs, or third-party game projects. Do not delete runtime data to reset code. Run engine integration checks in isolated test projects. Do not retry an ambiguous paid request automatically.

The UI supports Simplified Chinese and English. Preserve both locales and original user content; keep fixed interface strings in the translation catalogs. Keep unverified integrations labeled accurately. The workbench is local and single-user; do not expose it as a public web service or silently expand agent permissions.
