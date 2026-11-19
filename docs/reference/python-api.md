# Python API

Generated from the source by sphinx-autoapi on every docs build (nothing is imported, so the pages build without
KLayout, KQCircuits or AEDT).

- **quantcore_circuits**: the library (`Designer`, `design.json` schema, cells, router, assembly, DRC, LOM,
  simulation export, analysis, co-design loop).
- **qcc_kplugin**: the KLayout plugin's modules (they import `pya`, so they run only inside KLayout).

```{toctree}
:maxdepth: 2

api/quantcore_circuits/index
api/qcc_kplugin/index
```
