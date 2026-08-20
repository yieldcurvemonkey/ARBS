"""Mutation check for the SSGA/Vanguard providers.

A test that does not fail when its defect is reintroduced is decoration. Each entry
below re-creates a specific way this code could produce wrong data quietly, and asserts
that the named test goes red.

Run:  C:/Users/chris/anaconda3/envs/stir/python.exe tests/_mutate_etf_providers.py
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

MUTATIONS = [
    # ---------------------------------------------------------------- THE two that matter
    # 1. A refusal handed back as a response. This is the historical iShares defect
    #    reintroduced in the shared transport: the 403 body ("Access Denied") is not a
    #    holdings document, so parse() returns None and fetch() reports ABSENCE for a
    #    date the host simply refused. Mutating the final `raise Blocked` instead would
    #    trip an AttributeError rather than reproducing the real failure.
    ("MDP/ETFHoldings/providers/_base.py",
     "        if resp.status_code in BLOCKED_STATUSES:\n            last = f\"HTTP {resp.status_code}\"",
     "        if resp.status_code in BLOCKED_STATUSES:\n            return resp  # MUTATED: a refusal handed back as a response",
     "test_ssga_403_raises_blocked_rather_than_reporting_absence"),
    ("MDP/ETFHoldings/providers/_base.py",
     "        if resp.status_code in BLOCKED_STATUSES:\n            last = f\"HTTP {resp.status_code}\"",
     "        if resp.status_code in BLOCKED_STATUSES:\n            return resp  # MUTATED: a refusal handed back as a response",
     "test_vanguard_403_raises_blocked_rather_than_reporting_absence"),

    # 2. Vanguard's ignored asOfDate. Keying the row on the REQUEST is the whole defect:
    #    the endpoint answers 200 with a different date and says nothing.
    ("MDP/ETFHoldings/providers/vanguard.py",
     "    as_of = _as_of(doc[\"asOfDate\"])",
     "    as_of = requested  # MUTATED: trust the request the endpoint ignored",
     "test_vanguard_keys_on_the_document_date_not_the_requested_one"),
    ("MDP/ETFHoldings/providers/vanguard.py",
     "    url = BASE_URL.format(ticker=fund_id.lower())",
     "    url = BASE_URL.format(ticker=fund_id.lower()) + f\"?asOfDate={req}\"  # MUTATED",
     "test_vanguard_never_puts_the_ignored_date_on_the_wire"),

    # ---------------------------------------------------------------- supporting checks
    # 3. The SSGA header row read off a fixed offset instead of found.
    ("MDP/ETFHoldings/providers/ssga.py",
     "    hdr = _find_header_row(raw)",
     "    hdr = 4  # MUTATED: the header is where it was last Tuesday",
     "test_ssga_survives_a_preamble_line_being_added"),

    # 4. ISIN -> CUSIP by slicing, without the check digit. The money-market sweep and the
    #    USD cash line then arrive as nine-character strings that look like CUSIPs.
    ("MDP/ETFHoldings/providers/_base.py",
     "    if not s.startswith(\"US\") or not isin_check_digit_ok(s):\n        return None\n    return s[2:11]",
     "    return s[2:11] if len(s) >= 11 else None  # MUTATED: slice and hope",
     "test_isin_to_cusip_rejects_the_identifiers_that_merely_look_like_one"),

    # 5. The Vanguard cusip/isin tie-out dropped -- one field moving would then join to a
    #    real but different bond.
    ("MDP/ETFHoldings/providers/vanguard.py",
     "    clash = from_isin.notna() & wire_cusip.notna() & (from_isin != wire_cusip)",
     "    clash = from_isin.isna() & from_isin.notna()  # MUTATED: never clashes",
     "test_vanguard_refuses_a_payload_whose_cusip_and_isin_disagree"),

    # 5b. The percent/fraction units gate removed.
    ("MDP/ETFHoldings/providers/_base.py",
     "    if len(df) < WEIGHT_GATE_MIN_ROWS:\n        return",
     "    return  # MUTATED: trust whatever units the issuer sends",
     "test_a_weight_column_that_flips_to_fractions_is_refused"),

    # 6. A refusal writing a manifest row -- resume would honour the fabricated absence.
    ("MDP/ETFHoldings/backfill.py",
     "        where = f\"   pool: {pool.status()}\" if pool is not None else \"\"",
     "        store.write_manifest(ticker, [_manifest_row(today)])  # MUTATED: refusal as absence\n        where = f\"   pool: {pool.status()}\" if pool is not None else \"\"",
     "test_snapshot_does_not_write_a_manifest_row_when_it_is_refused"),

    # 7. A snapshot keyed on the run date rather than the document date.
    ("MDP/ETFHoldings/backfill.py",
     "    store.append_holdings(ticker, [hf.frame])",
     "    _f = hf.frame.copy(); _f[\"date\"] = pd.Timestamp(today)  # MUTATED: key on the run date\n    store.append_holdings(ticker, [_f])",
     "test_snapshot_stores_on_the_documents_date_and_records_the_request"),
]

env = dict(os.environ,
           ARBS_SUPABASE_ENABLED="0",
           ARBS_ETF_HOLDINGS_DIR="C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
py = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

print(f"{'test':62s} {'result':22s} anchor")
print("-" * 110)
ok = True
for rel, old, new, test in MUTATIONS:
    p = ROOT / rel
    src = p.read_text(encoding="utf-8")
    if old not in src:
        print(f"{test:62s} {'[SKIP] anchor gone':22s} {rel}")
        ok = False
        continue
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run(
            [py, "-m", "pytest", "tests/test_etf_providers.py", "-q", "-k", test],
            cwd=ROOT, capture_output=True, text=True, env=env, timeout=300)
        caught = r.returncode != 0
        print(f"{test:62s} {('[PASS] caught' if caught else '[FAIL] NOT CAUGHT'):22s} {rel}")
        ok &= caught
    finally:
        p.write_text(src, encoding="utf-8")

print("\nALL MUTATIONS CAUGHT" if ok else "\nSOME TESTS ARE DECORATION")
sys.exit(0 if ok else 1)
