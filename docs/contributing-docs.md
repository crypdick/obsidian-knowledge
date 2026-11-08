# Contributing to the docs

The site uses Material for MkDocs. Run commands from the repository root.

## Preview and build

Install only the locked documentation dependencies and start a local preview:

```bash
uv sync --only-group docs --locked
uv run --only-group docs --locked mkdocs serve
```

Open the local URL printed by MkDocs. Changes to documentation reload the preview.
Before submitting a change, run the same strict build as CI:

```bash
uv run --only-group docs --locked mkdocs build --strict --site-dir "$(mktemp -d)"
```

Build outside the checkout so generated files do not enter package checks. Documentation
dependencies live in the `docs` group in `pyproject.toml` and are pinned in
`uv.lock`; update both when adding or upgrading a plugin.

## Where to edit

The home page includes `README.md`; edit it there. Keep installation and everyday
use in the README, with focused pages under `docs/` for other tasks. Add pages
to the nearest `.pages` file. Historical `docs/superpowers/` plans are excluded
from the site.

Keep one canonical home per topic and link elsewhere. Use relative links within
the site and GitHub URLs for files outside `docs/`.

Write guidance as concise goals and essential constraints. Include procedures
only when sequence affects correctness; leave routine choices to judgment.
Do not repeat procedures in reminders or examples.

## Publishing

The `Docs` GitHub Actions workflow builds documentation on pull requests and
pushes to `main` when documentation, the README, dependencies, or the workflow
change. Only pushes to `main` and manual runs on `main` deploy to GitHub Pages.

In the repository's **Settings > Pages > Build and deployment**, select
**GitHub Actions** as the source. The workflow uploads `site/` and deploys the
[documentation site](https://crypdick.github.io/obsidian-knowledge/).

Checkout must fetch the full Git history for page creation and revision dates.
New, uncommitted pages use the build date during local previews.
