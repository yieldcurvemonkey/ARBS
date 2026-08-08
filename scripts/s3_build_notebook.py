"""Build an .ipynb from a percent-format .py, then execute it.

The repo's citivelo_rv notebooks ship as a .py/.ipynb pair and jupytext is not
installed in the `stir` env, so this does the split by hand: `# %%` opens a code
cell, `# %% [markdown]` opens a markdown cell whose `# ` prefixes are stripped.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 \
     scripts/s3_build_notebook.py <path/to/source.py> [--no-exec] [--timeout N]
"""
import argparse
import pathlib
import sys

import nbformat as nbf
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


def split_cells(src: str):
    cells, kind, buf = [], "code", []

    def flush():
        if not buf:
            return
        body = "\n".join(buf).strip("\n")
        if not body.strip():
            return
        if kind == "markdown":
            body = "\n".join(ln[2:] if ln.startswith("# ") else
                             ("" if ln.strip() == "#" else ln) for ln in body.splitlines())
            cells.append(new_markdown_cell(body))
        else:
            cells.append(new_code_cell(body))

    for line in src.splitlines():
        if line.startswith("# %%"):
            flush()
            buf = []
            kind = "markdown" if "[markdown]" in line else "code"
            continue
        buf.append(line)
    flush()
    return cells


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--no-exec", action="store_true")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    src_path = pathlib.Path(args.source).resolve()
    nb = new_notebook(cells=split_cells(src_path.read_text(encoding="utf-8")),
                      metadata={"kernelspec": {"display_name": "Python 3",
                                               "language": "python", "name": "python3"},
                                "language_info": {"name": "python"}})
    out = src_path.with_suffix(".ipynb")
    nbf.write(nb, str(out))
    n_code = sum(1 for c in nb.cells if c.cell_type == "code")
    print(f"wrote {out.name}: {len(nb.cells)} cells ({n_code} code)")

    if args.no_exec:
        return 0

    from nbclient import NotebookClient
    nb2 = nbf.read(str(out), as_version=4)
    client = NotebookClient(nb2, timeout=args.timeout, kernel_name="python3",
                            resources={"metadata": {"path": str(src_path.parent)}})
    try:
        client.execute()
    finally:
        nbf.write(nb2, str(out))
    errs = [(i, o) for i, c in enumerate(nb2.cells) if c.cell_type == "code"
            for o in c.get("outputs", []) if o.get("output_type") == "error"]
    print(f"executed with {len(errs)} errors")
    for i, o in errs[:3]:
        print(f"  cell {i}: {o.get('ename')}: {str(o.get('evalue'))[:200]}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
