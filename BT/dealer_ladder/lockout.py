"""One-shot enforcement for the holdout segment.

The pre-registration says the lockout is evaluated ONCE and that a failure burns the
configuration. As written that was a promise about my own behaviour, which is the
weakest kind of no-lookahead control: nothing in the code stopped a second run under a
quietly adjusted specification, and nothing recorded that the first run had happened.

So the claim is made mechanical. Claiming the lockout writes a record — the
fingerprint of the specification, the code vintage, the git SHA and the wall clock —
and a later claim under a DIFFERENT fingerprint is refused. Re-running the same
fingerprint is allowed and idempotent, because the same spec over the same data yields
the same number; that is a re-render, not a second shot.

The fingerprint deliberately covers the whole pre-registered config (window, universe,
signal, costs, primary spec, statistics), not just the primary block. Widening the
universe or moving the cost model changes the test as surely as moving the horizon
does, and the point of the gate is that no such change can be tried against the
holdout after seeing it.

What this cannot do is stop someone deleting the ledger file, and it is not meant to:
the ledger is committed alongside the findings, so a deletion is a visible act in the
history rather than an invisible one in a notebook.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess

LEDGER_NAME = "LOCKOUT_USED.json"


class LockoutAlreadyBurned(RuntimeError):
    """Raised when the holdout has already been evaluated under another spec."""


def _plain(obj):
    """A JSON-able, ORDER-STABLE view of a nested dataclass/dict/tuple config."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name))
                for f in sorted(dataclasses.fields(obj), key=lambda f: f.name)}
    if isinstance(obj, dict):
        return {str(k): _plain(obj[k]) for k in sorted(obj, key=str)}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def config_fingerprint(config) -> str:
    """12 hex chars over the WHOLE pre-registered configuration.

    Not just the primary block: widening the universe or softening the cost model
    changes the test exactly as much as moving the horizon does.
    """
    blob = json.dumps(_plain(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"],
                             capture_output=True, text=True, timeout=20,
                             cwd=os.path.dirname(os.path.abspath(__file__)))
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def ledger_path(results_dir: str) -> str:
    return os.path.join(results_dir, LEDGER_NAME)


def read_ledger(results_dir: str) -> dict | None:
    path = ledger_path(results_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        # An unreadable ledger must not be treated as an unused lockout: that is the
        # one failure mode that would silently hand back a second shot.
        return {"spec_fingerprint": "UNREADABLE", "note": "ledger could not be parsed"}


def is_claimed(results_dir: str) -> bool:
    return read_ledger(results_dir) is not None


def claim(config, results_dir: str, *, note="", timestamp=None,
          code_vintage=None, force=False) -> dict:
    """Record the single permitted evaluation of the holdout, or refuse.

    Returns the ledger record. Raises ``LockoutAlreadyBurned`` when a record exists
    under a different fingerprint, unless ``force`` — which exists only so that a
    deliberate, documented re-registration is possible, and which stamps the record so
    the override is never invisible.
    """
    fp = config_fingerprint(config)
    prior = read_ledger(results_dir)
    if prior is not None and prior.get("spec_fingerprint") != fp and not force:
        raise LockoutAlreadyBurned(
            "The holdout has already been evaluated under a DIFFERENT specification "
            f"(recorded {prior.get('spec_fingerprint')} at "
            f"{prior.get('claimed_at')}, now asked for {fp}). The pre-registration "
            "allows one shot: a second specification tested against the same holdout "
            "is a fitted result reported as an out-of-sample one. To re-register "
            "deliberately, pass force=True and say why in the findings doc — the "
            "override is stamped into the ledger.")
    if prior is not None and prior.get("spec_fingerprint") == fp:
        return prior          # idempotent: same spec, same data, same answer

    rec = {
        "spec_fingerprint": fp,
        "claimed_at": timestamp,
        "git_sha": _git_sha(),
        "code_vintage": code_vintage,
        "note": note,
        "overrode_prior": (prior or {}).get("spec_fingerprint") if force else None,
        "config": _plain(config),
    }
    os.makedirs(results_dir, exist_ok=True)
    with open(ledger_path(results_dir), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, default=str)
    return rec
