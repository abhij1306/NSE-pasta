---
name: fix-source
description: Diagnose and fix an NSE-pasta source that `pasta doctor` reports as not_found, blocked or format_changed - find where NSE moved an endpoint, set it in pasta.toml, or make the parser change with a recorded fixture and a test. Use when fetches keep failing or doctor is not all ok.
---

# Fix a broken source

Reference: `docs/maintaining.md`, `docs/sources.md`.

1. Run `uv run pasta --data D doctor` and note each source that is not `ok`.
2. `blocked`: wait and retry once with a larger `[network] interval` (never below 2 s). Do not
   add headers, rotate user agents or otherwise work around a block: report it.
3. `not_found`: open the matching page on nseindia.com in a browser (the `*_page` URLs in
   `docs/sources.md`), watch the network requests it makes, and find the new endpoint. Set it
   under `[sources]` in `D/pasta.toml`, rerun `doctor`. If the change is permanent, update the
   default in `src/nse_pasta/config.py` and `docs/sources.md`.
4. `format_changed`: save one real answer, trim it (`scripts/trim_fixture.py` for XBRL; keep two
   or three rows of a JSON listing), add it under `tests/fixtures/`, write the failing test
   first, then change the parser. Never parse by guesswork: an answer in an unknown shape must
   fail loudly (`doctor`) or be excluded with a reason (`out/filings.csv`).
5. screener.in: if its robots.txt no longer allows `/company/<SYMBOL>/`, pasta stops asking by
   design. Do not change that; say so.
6. `uv run pytest` and `uv run ruff format --check . && uv run ruff check .` before proposing
   the change.
