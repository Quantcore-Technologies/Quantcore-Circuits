# Building these docs

Questions about building and hosting this documentation. The full guide is [Building and hosting](../hosting.md).

## Building

### How do I build the docs?

In the separate `qcc-docs` env, not `qcd`: `pip install -r docs/requirements.txt`, then
`sphinx-build -b html docs docs/_build/html`. The API pages are read from the source by sphinx-autoapi, so the build
needs neither KLayout, KQCircuits nor AEDT. `docs/_build/` is git-ignored. See [Building and hosting](../hosting.md).

### The build takes long while I write pages. Can I skip the API?

Yes: set `QCC_DOCS_FAST=1`. It skips the API reference, so a build takes seconds to a minute. A full build writes `docs/reference/api/` into the source tree
while it runs.

### Where do the component pages come from?

They are generated: `python scripts/make_docs.py` in the `qcd` env writes one page per component (pin picture, pins table,
parameters and LOM) and the `qcc` reference; `--render` also draws pictures for new components. Hand-written notes go in
`docs/components/notes/<Cell>.md`. Commit the regenerated pages: the hosted docs only render what is in the repository.

### Where do I put images?

In `docs/images/<topic>/`, linked relatively from the page.

### Can I use tabs or cards in a page?

No. Only MyST Markdown with tables, admonitions, figures, toctrees and math is available; sphinx-design and
sphinx-togglebutton are not installed.

## Hosting

### How do I host the docs?

The docs are published on GitHub Pages at <https://quantcore-technologies.github.io/Quantcore-Circuits/>. You can also
build them locally and copy `docs/_build/html` to any web server. See [Building and hosting](../hosting.md).

### Can I host the docs on Read the Docs?

The free readthedocs.org serves public sites only. The repository is public and licensed GPL-3.0-or-later (the code
builds on KQCircuits), so a public host works.
