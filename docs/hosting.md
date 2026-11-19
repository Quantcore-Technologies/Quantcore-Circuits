# Building and hosting these docs

The docs are a [Sphinx](https://www.sphinx-doc.org) site written in Markdown
([MyST](https://myst-parser.readthedocs.io)). The source is the `docs/` folder. The API pages are read from the source
code by sphinx-autoapi, so building the docs needs neither KLayout, KQCircuits nor AEDT.

## What is where

| Path | What |
|---|---|
| `docs/conf.py` | Sphinx settings: theme, MyST options, API reference |
| `docs/index.md` | Home page and the table of contents (the `toctree` blocks) |
| `docs/requirements.txt` | The docs toolchain (Sphinx, MyST, Furo, sphinx-autoapi, sphinx-copybutton) |
| `.github/workflows/docs.yml` | The GitHub Actions workflow that builds and publishes the site |
| `docs/components/cells/` | **Generated**: one page per component (pins, parameters, LOM) |
| `docs/components/notes/<Cell>.md` | Hand-written notes, included in that cell's generated page |
| `docs/reference/cli.md` | **Generated**: the `qcc` command reference |
| `docs/images/` | Images used by the pages: `components/` (pin pictures), `designs/` (design snapshots), `plugin/` (plugin screenshots, linked from `kplugin/*.md` as `../docs/images/plugin/…`) |
| `docs/plugin/TUTORIAL_q1_r1.md`, `docs/plugin/COMPONENTS_STATUS.md`, `docs/dev/index.md` | Thin pages that include `kplugin/TUTORIAL_q1_r1.md`, `kplugin/COMPONENTS_STATUS.md` and `CONTRIBUTING.md`, so those files stay the one place to edit |

## Build locally

Use a separate env for the docs tools, so the `qcd` env stays as tested:

```bat
conda create -n qcc-docs python=3.11
conda activate qcc-docs
pip install -r docs/requirements.txt
sphinx-build -b html docs docs/_build/html
start docs\_build\html\index.html
```

`docs/_build/` is git-ignored. For a live preview while you write, `pip install sphinx-autobuild` and run
`sphinx-autobuild docs docs/_build/html`.

## Regenerate the generated pages

These need the `qcd` env, because they build the cells with the library:

```bat
conda activate qcd
python scripts/make_docs.py                 REM component pages + qcc reference
python scripts/make_docs.py --render        REM also draw pin pictures for new components
```

Commit the regenerated pages. The publishing workflow only renders them; it does not run the library.

## Add a page

1. Write a `.md` file under `docs/`, for example `docs/plugin/routing.md`.
2. Add its path (without `.md`) to a `toctree` block in `docs/index.md`, or in a section page.
3. Put its images in `docs/images/<topic>/` and link them relatively: `![Connect tool](../images/plugin/connect.png)`.

MyST adds a few blocks to plain Markdown:

````md
:::{note}
A note box.
:::

```{include} ../../kplugin/README.md
```
````

## Host it

The docs are published on GitHub Pages at <https://quantcore-technologies.github.io/Quantcore-Circuits/>. The workflow
`.github/workflows/docs.yml` installs `docs/requirements.txt`, runs the same `sphinx-build -b html docs` as the local
build (with the API reference) and deploys the result to GitHub Pages. It runs on every push to `main` and can be started
by hand from the repository's **Actions** tab. In the repository's **Settings > Pages**, the source must be set to
**GitHub Actions**.

To check what the workflow will publish, build locally as above. For a quick look on one machine without a browser
file URL: `python -m http.server -d docs/_build/html 8000`, then open <http://localhost:8000>. To host a copy
elsewhere, copy `docs/_build/html` to any web server or file share.
