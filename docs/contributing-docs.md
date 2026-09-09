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
uv run --only-group docs --locked mkdocs build --strict
```

MkDocs writes the generated site to `site/`, which Git ignores. Documentation
dependencies live in the `docs` group in `pyproject.toml` and are pinned in
`uv.lock`; update both when adding or upgrading a plugin.

## Where to edit

- The home page includes the repository's `README.md`; edit that file directly.
- Add focused Markdown pages under `docs/` and order them in the nearest `.pages`
  file. Use relative Markdown links between site pages.
- Keep each topic in one canonical place and link to it from other pages.
- Lead with the reader's task. Keep installation and everyday use in the README;
  put configuration, troubleshooting, and contributor details on focused pages.
- Keep prompts limited to decisions, constraints, and commands the agent needs.
  Avoid repeating procedures in reminders or examples.
- Historical plans and specs in `docs/superpowers/` are excluded from the site.
- Link files outside `docs/` using their GitHub URL so links also work on the site.

## Publishing

The `Docs` GitHub Actions workflow builds documentation on pull requests and
pushes to `main` when documentation, the README, dependencies, or the workflow
change. Only pushes to `main` and manual runs on `main` deploy to GitHub Pages.

In the repository's **Settings > Pages > Build and deployment**, select
**GitHub Actions** as the source. The workflow uploads `site/` and deploys the
[documentation site](https://crypdick.github.io/obsidian-knowledge/).

Checkout must fetch the full Git history for page creation and revision dates.
New, uncommitted pages use the build date during local previews.
