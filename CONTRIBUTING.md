# Contributing

Thanks for helping improve Supertonic Server. Bug reports, fixes, docs and new ideas are
all welcome. By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Security problems go through the private process in [SECURITY.md](SECURITY.md), not
public issues.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Git. uv installs a suitable Python
(3.11 to 3.13) for you.

```bash
git clone https://github.com/saifulbabo67646/supertonic.git
cd supertonic
uv sync                       # creates .venv with runtime and dev dependencies
uv run pre-commit install     # runs ruff and mypy on every commit
uv run supertonic-server serve   # http://127.0.0.1:8787 (downloads the model on first run)
```

The voice builder needs an NVIDIA GPU and the optional extra: `uv sync --extra builder`
(see [docs/builder.md](docs/builder.md)). Everything else, including the builder tests,
runs without it.

Coding agents: [AGENTS.md](AGENTS.md) has the same steps as a checklist, plus how to run
the server in the background and smoke-test it (`uv run supertonic-server check`).

## Tests and checks

```bash
uv run pytest                 # unit and API tests; real-model and GPU tests are skipped
uv run pytest -m model        # needs the real Supertonic weights
uv run pytest -m gpu          # needs a CUDA GPU, the builder extra and real weights
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

CI runs lint and type checks, then the tests on Linux, macOS and Windows with Python
3.11, 3.12 and 3.13, and checks that the package builds. Please run the commands above
before opening a pull request.

## Code style

- Python: full type hints (`mypy --strict` clean), formatted and linted with ruff (line
  length 100), Google-style docstrings on public functions and classes, `logging` instead
  of `print`.
- Keep modules small (about 300 lines at most) and split them along a real seam when they
  grow. Each subpackage lists its public names in `__all__`.
- Domain packages (`engine`, `voices`, `audio`, `text`, `builder`) never import from
  `api` or `mcp`; routes depend on the domain, not the other way round.
- Web UI: plain ES modules in `src/supertonic_server/web/js/`, no build step. Keep files
  under about 300 lines and write UI text in plain, friendly words.
- Tests sit next to their layer: `tests/unit/`, `tests/api/`, `tests/mcp/`. Use the fakes
  in `tests/fakes.py` and `tests/fakes_builder.py` instead of real models.

## Commits and pull requests

1. Fork the repository and create a branch from `main` (`fix/short-name`,
   `feat/short-name`).
2. Write [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
   `docs:`, `test:`, `refactor:`, `build:`, `ci:`, `chore:`. Keep each commit focused.
3. Add or update tests for any behaviour change and add a line under `Unreleased` in
   [CHANGELOG.md](CHANGELOG.md).
4. Open a pull request and fill in the template. CI must pass; a maintainer will review
   it, and may ask for changes before merging.

No contributor licence agreement or sign-off is needed: contributions are accepted under
the project's [MIT licence](LICENSE).

## Adding a route

1. Add request/response models to `src/supertonic_server/api/schemas.py`.
2. Create the handler in `src/supertonic_server/api/routes/<name>.py` with an `APIRouter`.
3. Add the router to `ROUTERS` in `api/routes/__init__.py`; raise `ApiError` for failures.
4. Add tests under `tests/api/` and document the route in [docs/api.md](docs/api.md).

## Adding a language

1. Add the code and display name to `src/supertonic_server/text/languages.py`.
2. Make sure it is accepted by `supertonic.config.SUPPORTED_LANGUAGES`.
3. Add a sanitising/segmentation test in `tests/unit/test_text.py`.
