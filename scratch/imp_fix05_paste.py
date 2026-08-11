"""Paste the generated CAP_BANDS literal into the module. Never by hand."""
import io
import os
import re

ROOT = r"C:\Users\chris\clee\ARBS-dd"
MOD = os.path.join(ROOT, "SDRUtils", "dealer_direction", "imputation.py")
LIT = os.path.join(ROOT, "scratch", "imp_fix01_cap_bands.txt")

with io.open(MOD, encoding="utf-8") as fh:
    src = fh.read()
with io.open(LIT, encoding="utf-8") as fh:
    lit = fh.read().rstrip("\n")

pat = re.compile(r"^CAP_BANDS: tuple\[CapBand, \.\.\.\] = \(\n.*?^\)$",
                 re.S | re.M)
new, n = pat.subn(lambda m: lit, src)
assert n == 1, f"expected exactly one CAP_BANDS block, found {n}"
assert new != src, "no change"
with io.open(MOD, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(new)
print(f"replaced CAP_BANDS ({len(lit.splitlines())} lines)")
