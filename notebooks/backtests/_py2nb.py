"""Convert a ``# %%``-delimited script into a Jupyter notebook.

Percent-format cells (the same convention jupytext uses) keep the framework
sources readable and diffable as plain Python while still producing the
executed ``.ipynb`` deliverables. ``# %% [markdown]`` starts a markdown cell;
its body is the comment block that follows.

Usage::

    python notebooks/backtests/_py2nb.py sfr_rv_lab_skew_basis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List


def split_cells(src: str) -> List[dict]:
    cells: List[dict] = []
    kind, buf = "code", []

    def flush():
        if not buf:
            return
        text = "\n".join(buf).strip("\n")
        if not text.strip():
            return
        if kind == "markdown":
            body = "\n".join(
                l[2:] if l.startswith("# ") else ("" if l.strip() == "#" else l)
                for l in text.splitlines()
            )
            cells.append({"cell_type": "markdown", "metadata": {},
                          "source": body.splitlines(keepends=True)})
        else:
            cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                          "outputs": [], "source": text.splitlines(keepends=True)})

    for line in src.splitlines():
        if line.startswith("# %%"):
            flush()
            buf = []
            kind = "markdown" if "[markdown]" in line else "code"
            continue
        buf.append(line)
    flush()
    return cells


def convert(py_path: Path, nb_path: Path | None = None) -> Path:
    nb_path = nb_path or py_path.with_suffix(".ipynb")
    nb = {
        "cells": split_cells(py_path.read_text(encoding="utf-8")),
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return nb_path


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        print(convert(p))
