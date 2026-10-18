# Contributing

Thanks for helping improve Supertonic Server.

## Setup

```bash
git clone <repo-url> && cd supertonic
uv sync                 # creates .venv and installs runtime + dev dependencies
uv run pre-commit install
```

## Tests and lint

```bash
uv run pytest                 # unit/API tests (real-model tests are skipped)
uv run pytest -m model        # needs real Supertonic weights
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

CI runs the same commands on Linux, macOS and Windows with Python 3.11-3.13.

## Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `test:`, `refactor:`, `chore:`. Keep commits focused and update `CHANGELOG.md`.

## Adding a route

1. Add request/response models to `src/supertonic_server/api/schemas.py`.
2. Create the handler in `src/supertonic_server/api/routes/<name>.py` with an `APIRouter`.
3. Register the router in `api/app.py`; raise `ApiError` for failures.
4. Add tests under `tests/api/`.

Routes may depend on domain packages (`engine`, `voices`, `audio`, `text`), never the reverse.

## Adding a language

1. Add the code and display name to `src/supertonic_server/text/languages.py`.
2. Make sure it is accepted by `supertonic.config.SUPPORTED_LANGUAGES`.
3. Add a sanitising/segmentation test in `tests/unit/test_text.py`.

## Code standards

Full type hints (`mypy --strict` clean), ruff-formatted (line length 100), docstrings on
public APIs, modules under ~300 lines, `logging` instead of `print`.
