"""Check every markdown table has a consistent cell count, splitting the way GFM does.

GFM splits a table row on `|` BEFORE inline code is parsed, so a pipe inside backticks still
starts a new cell; only `\\|` escapes it. Pipe-delimited variant names
(`FUTURES->FUTURES|hl30|expected|h5`) therefore broke 109 rows until the renderers were taught to
escape them.
"""
import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

P = sys.argv[1] if len(sys.argv) > 1 else \
    "docs/superpowers/plans/2026-07-30-dealer-ladder-signal-findings.md"
lines = io.open(P, encoding="utf-8").read().splitlines()

UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
DIVIDER = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def cells(line):
    return len(UNESCAPED_PIPE.findall(line))


issues, tables, i = [], 0, 0
while i < len(lines):
    if (lines[i].strip().startswith("|") and i + 1 < len(lines)
            and DIVIDER.match(lines[i + 1])):
        tables += 1
        n = cells(lines[i])
        j = i + 2
        while j < len(lines) and lines[j].strip().startswith("|"):
            if cells(lines[j]) != n:
                issues.append((j + 1, cells(lines[j]), n, lines[j][:78]))
            j += 1
        i = j
    else:
        i += 1

print(f"{P}\n  tables {tables} | malformed rows {len(issues)}")
for ln, got, want, ctx in issues[:10]:
    print(f"  line {ln}: {got} cells vs header {want}\n    {ctx}")
sys.exit(1 if issues else 0)
