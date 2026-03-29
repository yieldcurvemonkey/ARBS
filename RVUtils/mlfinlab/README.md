# mlfinlab (vendored)

This directory vendors a legacy `mlfinlab` 0.4.1 snapshot into the ARBS repository.

## Install

```powershell
pip install -e RVUtils/mlfinlab
```

## Notes

- The legacy reference PDF is included at `RVUtils/mlfinlab/mlfinlab Release Hudson & Thames.pdf`.
- This snapshot is not a full upstream release; many modules are still placeholders.
- The ARBS integration work here focuses on making the package buildable/importable and on the documented dataset/filter workflows used by the example notebook.
