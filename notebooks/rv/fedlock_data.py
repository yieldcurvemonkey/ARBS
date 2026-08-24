r"""FedLock V3 as a Fed sentiment input for the data-surprise lead study.

FedLock (https://jnathan9.github.io/fedlock/) scores Fed speeches on a
hawkish-dovish scale by running a **pairwise tournament**: an anonymised judge
model reads two speeches side by side with the macro conditions of the day and
picks the more hawkish, and a TrueSkill engine turns ~60,000 of those binary
decisions into a continuous rating. V3 (August 2026) uses Llama 3.3 70B.

This module supplies that series in the shape
``fed_sentiment_lead_data`` already consumes, so the lead can be re-measured
with **the identical estimator and the identical frozen config** on a different
sentiment model and a twenty-year sample. Any difference in the answer is then
attributable to the data, which is the whole point of the exercise.

What FedLock buys, and what it costs
------------------------------------
**Buys: length.** 3,673 dated speeches from 1985, against the JPM corpus's 730
from 2008 with a point-in-time-usable window starting 2023-05. Overlapped with
Citi's daily surprise indices the study window is ~2005-2026, roughly **1,100
weekly observations against 147**. That is enough to split by decade, which is
the test the first study could not run.

**Costs: it can never be point-in-time.** Not "is not" -- *cannot be*, through
three separate channels:

1. **One vintage.** There is no per-row publication or ingestion date. The whole
   file carries a single ``builtOn`` stamp. Nothing to gate on.
2. **Joint estimation.** TrueSkill fits every rating simultaneously from a graph
   of pairwise comparisons. A 2007 speech's score depends on the speeches it was
   compared against, which are drawn from the whole 1985-2026 corpus. Future
   information is in every historical score by construction, and no masking
   undoes it because the number itself was produced that way.
3. **The judge's own training.** Llama 3.3 has read decades of commentary about
   these speeches and about what the Fed did next. Anonymisation strips names,
   not hindsight. Only speeches after the model's cutoff are scored blind. This
   is the channel FedLock's methodology does not address, and it is a caveat
   rather than a disqualifier -- but it is real, and it points the same way as
   the other two.

So this study is **as-published only, and nothing in it is tradeable**. The pair
of studies is the point: the first is tradeable over 147 weeks, this one is
un-gateable over 1,100. A lead worth acting on would have to survive both.

Related: ``fed_sentiment_lead_data`` (the estimator, unchanged),
``project_fed_sentiment_lead``, ``reference_lead_lag_filter_offset``.
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import pathlib
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(REPO), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_sentiment_lead_data as D  # noqa: E402

#: The live dataset, and the frozen predecessor kept for the revision measurement.
URL_V3 = "https://jnathan9.github.io/fedlock/v3/data.json"
URL_V2 = "https://jnathan9.github.io/fedlock/v2/data.json"

DEFAULT_SNAPSHOT = HERE / "fedlock_v3_snapshot.parquet"
DEFAULT_SNAPSHOT_V2 = HERE / "fedlock_v2_snapshot.parquet"

#: Columns kept in the snapshot. The full payload carries titles, URLs and a
#: macro block this study does not read; trimming takes it from ~1.1 MB to tens
#: of KB and makes the parquet reviewable in a diff.
KEEP = ("date", "m", "ma", "s", "n", "speaker", "speech_type", "source", "title")

#: FedLock's own hawk/dove roster, used as an external known-answer for the
#: speaker cross-section. Not used to build anything.
HAWKS = ("Hoenig", "Plosser", "Fisher", "Lacker", "Bowman", "Waller", "George",
         "Schmid", "Bullard", "Logan", "Mester")
DOVES = ("Brainard", "Evans", "Rosengren", "Kocherlakota", "Daly", "Kashkari",
         "Cook", "Bostic")


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def parse_payload(payload: dict) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """The published JSON as a tidy frame, plus its provenance.

    The ``d`` field is not always a date: 327 of the 4,000 V3 rows carry a bare
    year (``"2008"``), which is what the regional-Fed scrapers could recover.
    Those rows are dropped -- placing them at an arbitrary point inside their
    year would fabricate the one property this study measures -- and the hole is
    reported rather than absorbed.
    """
    sp = pd.DataFrame(payload["speeches"]).rename(
        columns={"a": "speaker", "st": "speech_type", "src": "source", "tt": "title"}
    )
    # Only a full ISO date counts. Handing the raw column to pd.to_datetime is
    # not safe here: it infers ONE format from the first non-null value, so with
    # a mix of "1985-07-25" and "2008" the set of rows that fail to parse
    # depends on the ORDER of the file. Real payloads happen to start with a
    # full date, which is exactly why that would have gone unnoticed. Matching
    # the format explicitly makes the classification a property of each value.
    iso = sp["d"].astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    sp["date"] = pd.to_datetime(sp["d"].where(iso), format="%Y-%m-%d", errors="coerce")
    undated = sp[sp["date"].isna()].copy()
    dated = sp.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    cfg = payload.get("config", {}) or {}
    prov = {
        "built_on": cfg.get("builtOn"),
        "data_through": cfg.get("dataThrough"),
        "n_rows": int(len(sp)),
        "n_dated": int(len(dated)),
        "n_undated": int(len(undated)),
        "undated_by_speaker": undated["speaker"].value_counts().head(8).to_dict(),
        "undated_by_source": undated["source"].value_counts().to_dict()
        if "source" in undated else {},
        "undated_mean_score": float(undated["m"].mean()) if len(undated) else np.nan,
        "dated_mean_score": float(dated["m"].mean()),
    }
    keep = [c for c in KEEP if c in dated.columns]
    return dated[keep], prov


def read_snapshot(path: pathlib.Path = DEFAULT_SNAPSHOT) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def snapshot_provenance(path: pathlib.Path = DEFAULT_SNAPSHOT) -> Dict[str, object]:
    meta = path.with_suffix(".json")
    if not meta.exists():
        return {"source": "unknown", "note": "no sidecar"}
    return json.loads(meta.read_text(encoding="utf-8"))


def load_speeches(
    *, snapshot: pathlib.Path = DEFAULT_SNAPSHOT
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """The committed snapshot, never the network.

    Refreshing is an explicit act (``fedlock_refresh.py``), for the same reason
    the surprise side is: a notebook that silently re-fetches is a notebook
    whose numbers change under the reader. It matters more here than there --
    **a FedLock refresh is a new vintage in which HISTORY MOVES**, because new
    speeches enter the tournament and shift the TrueSkill ratings of old ones.
    """
    if not pathlib.Path(snapshot).exists():
        raise FileNotFoundError(
            f"{snapshot} missing -- run: python notebooks/rv/fedlock_refresh.py"
        )
    return read_snapshot(pathlib.Path(snapshot)), snapshot_provenance(
        pathlib.Path(snapshot)
    )


def to_score_book(
    speeches: pd.DataFrame,
    *,
    score_column: str = "m",
    speech_types: Optional[Tuple[str, ...]] = None,
    min_comparisons: int = 0,
    max_sigma: Optional[float] = None,
) -> pd.DataFrame:
    """FedLock rows in the shape ``sentiment_index`` consumes.

    The estimator wants ``date``, ``pub_date``, ``speaker``, ``hawk_dove_score``
    and ``relevance_pct``. ``pub_date`` is set equal to ``date`` deliberately and
    loudly: it is not a claim that the score was knowable then, it is the
    encoding of "this dataset has no publication axis at all", and the
    point-in-time path must never be run against it. :func:`gate_single_vintage`
    is what enforces that.
    """
    df = speeches.copy()
    if speech_types is not None:
        df = df[df["speech_type"].isin(speech_types)]
    if min_comparisons:
        df = df[df["n"] >= min_comparisons]
    if max_sigma is not None:
        df = df[df["s"] <= max_sigma]
    out = pd.DataFrame(
        {
            "central_bank": "FED",
            "date": pd.to_datetime(df["date"]),
            "pub_date": pd.to_datetime(df["date"]),
            "speaker": df["speaker"].astype(str).str.split().str[-1],
            "speaker_full": df["speaker"].astype(str),
            "hawk_dove_score": df[score_column].astype(float),
            "relevance_pct": 50.0,
            "sigma": df["s"].astype(float),
            "n_comparisons": df["n"].astype(float),
            "speech_type": df["speech_type"].astype(str),
        }
    )
    return out.dropna(subset=["hawk_dove_score"]).sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------
def gate_single_vintage(speeches: pd.DataFrame, prov: Dict[str, object]) -> Dict[str, object]:
    """G7 -- assert this dataset has no publication axis, and say so loudly.

    The first study's central discipline was gating on ``pub_date``. Here there
    is nothing to gate on, and the danger is that a reader assumes otherwise
    because the machinery has a ``point_in_time`` switch. So this asserts the
    absence rather than leaving it implicit.
    """
    forbidden = {"pub_date", "published", "ingested_at", "scraped_at", "vintage",
                 "as_of", "first_seen"}
    present = forbidden.intersection(set(speeches.columns))
    assert not present, (
        f"G7 FAILED: FedLock is documented as single-vintage but the frame carries "
        f"{sorted(present)} -- if a real publication axis has appeared, the study "
        f"should be gated on it instead of declaring the gate impossible"
    )
    assert prov.get("built_on"), "G7 FAILED: no builtOn stamp -- the vintage is unknown"
    return {
        "built_on": prov["built_on"],
        "data_through": prov.get("data_through"),
        "row_level_vintage_fields": 0,
        "verdict": "single vintage, jointly estimated -- no point-in-time series exists",
    }


def gate_era_adjustment(speeches: pd.DataFrame) -> Dict[str, float]:
    """G8 -- tie ``ma`` out to its published definition.

    FedLock states ``adjusted = raw - quarterly mean + 50``. Reconstructing it is
    a known-answer check on the column, and the residual is informative: it is
    non-zero because the quarterly mean is taken over ALL speeches including the
    undated ones this study drops, which cannot be placed in a quarter here.
    """
    o = speeches.dropna(subset=["date"]).sort_values("date")
    qmean = o.groupby(o["date"].dt.to_period("Q"))["m"].transform("mean")
    recon = o["m"] - qmean + 50.0
    corr = float(np.corrcoef(o["ma"], recon)[0, 1])
    resid = (o["ma"] - recon).abs()
    assert corr > 0.99, (
        f"G8 FAILED: `ma` does not reconstruct as raw - quarterly mean + 50 "
        f"(corr {corr:.4f}) -- the era adjustment is not what the methodology says"
    )
    return {"corr": corr, "mean_abs_resid": float(resid.mean()),
            "max_abs_resid": float(resid.max()), "n": int(len(o))}


def known_answer_speaker_ranking(
    speeches: pd.DataFrame, *, score_column: str = "ma", min_speeches: int = 20
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """FedLock's published cross-section claims, checked.

    **Use the era-adjusted column.** The published Rankings tab is era-adjusted,
    and raw means are dominated by the era a speaker served in -- the 2020s
    corpus mean is 53.9 against the 2010s' 47.7, so ranking on raw floats anyone
    who spoke recently to the top and sinks the ZIRP-era hawks. Checking the
    published claim against the wrong column produces a false failure.
    """
    o = speeches.dropna(subset=["date"])
    g = (o.groupby("speaker")[score_column].agg(["count", "mean"])
         .query(f"count >= {min_speeches}").sort_values("mean", ascending=False))
    ranks = {name: i + 1 for i, name in enumerate(g.index)}

    def _rank(surname: str) -> Optional[int]:
        """Match on a whole NAME TOKEN, never a substring.

        ``"Schmid" in "Susan Schmidt Bies"`` is true, and it would silently
        resolve one of FedLock's named hawks to a different speaker -- which
        would move the pair-separation statistic that licenses using this series
        at all. Tokenising the full name closes it.
        """
        target = surname.lower()
        for full, r in ranks.items():
            if target in [tok.lower().strip(".,") for tok in str(full).split()]:
                return r
        return None

    hawk_ranks = [r for r in (_rank(h) for h in HAWKS) if r]
    dove_ranks = [r for r in (_rank(d) for d in DOVES) if r]
    pairs = [(h < d) for h in hawk_ranks for d in dove_ranks]
    return g, {
        "n_speakers": int(len(g)),
        "hawk_ranks": {h: _rank(h) for h in HAWKS},
        "dove_ranks": {d: _rank(d) for d in DOVES},
        "median_hawk_rank": float(np.median(hawk_ranks)) if hawk_ranks else np.nan,
        "median_dove_rank": float(np.median(dove_ranks)) if dove_ranks else np.nan,
        "pair_separation": float(np.mean(pairs)) if pairs else np.nan,
        "score_column": score_column,
    }


def gaussian_trend(speeches: pd.DataFrame, *, score_column: str = "m",
                   sigma_days: float = 45.0, anchor: str = "W-FRI") -> pd.Series:
    """FedLock's own Timeline construction: Gaussian-weighted, sigma 45d, weekly.

    Reproduced exactly so its published peak (Q3-2022) and trough (Q2-2020) can
    be checked. It is **not** the series this study measures the lead on -- that
    uses the same causal EWMA the first study used, so the two studies share an
    estimator. A symmetric Gaussian kernel looks forward as well as back.
    """
    s = speeches.dropna(subset=["date"]).set_index("date")[score_column].astype(float)
    grid = pd.date_range(s.index.min(), s.index.max(), freq=anchor)
    sd = s.index.values.astype("datetime64[D]").astype(float)
    sv = s.to_numpy(float)
    out = []
    for t in grid:
        td = np.datetime64(t.date(), "D").astype(float)
        w = np.exp(-0.5 * ((sd - td) / float(sigma_days)) ** 2)
        out.append(np.nan if w.sum() < 1e-9 else float(np.sum(w * sv) / np.sum(w)))
    return pd.Series(out, index=grid, name="fedlock_trend").dropna()


def compare_vintages(v2: pd.DataFrame, v3: pd.DataFrame) -> Dict[str, object]:
    """How far the whole history moves when the judge model changes.

    This is FedLock's analogue of the first study's revision measurement, and it
    is the more alarming of the two: there, a re-score moved individual weeks;
    here, swapping Gemini 2.0 Flash for Llama 3.3 70B re-rates the entire corpus
    at once, and every historical score moves together.
    """
    key = ["date", "speaker", "title"]
    missing = [k for k in key if k not in v2.columns or k not in v3.columns]
    # Falling back to a shorter key is not a graceful degradation here: a speaker
    # with two speeches on one day would CROSS-JOIN, pairing V2's score for one
    # against V3's score for the other, and this merge is the sole input to the
    # 51%-of-a-standard-deviation headline. Refuse instead.
    assert not missing, (
        f"compare_vintages needs {key}; missing {missing} from one of the "
        f"snapshots. A shorter key cross-joins same-day speeches and would "
        f"inflate the measured move."
    )
    m = v2[key + ["m", "ma"]].merge(v3[key + ["m", "ma"]], on=key, how="inner",
                                    suffixes=("_v2", "_v3"))
    if len(m) < 50:
        return {"matched": int(len(m)), "note": "too few matches to compare"}
    out: Dict[str, object] = {"matched": int(len(m)), "n_v2": int(len(v2)),
                              "n_v3": int(len(v3))}
    for c in ("m", "ma"):
        a, b = m[f"{c}_v2"], m[f"{c}_v3"]
        d = (b - a).abs()
        out[c] = {
            "pearson": float(np.corrcoef(a, b)[0, 1]),
            "spearman": float(a.corr(b, method="spearman")),
            "mean_abs_move": float(d.mean()),
            "p90_abs_move": float(d.quantile(0.90)),
            "max_abs_move": float(d.max()),
            "sd_v3": float(b.std()),
            "move_in_sd": float(d.mean() / b.std()),
        }
    return out


def cross_model_agreement(
    fedlock: pd.DataFrame, jpm: pd.DataFrame, *, start: str = "2023-05-02"
) -> Dict[str, object]:
    """FedLock against the JPM NLP corpus on the speeches both scored.

    If two independent models disagree about which speeches were hawkish, then a
    lead measured on either is a property of that model as much as of the Fed,
    and neither study's number generalises. This is the cheapest test of that
    and it belongs before any lead is quoted.
    """
    f = fedlock[fedlock["date"] >= pd.Timestamp(start)].copy()
    f["surname"] = f["speaker"].astype(str).str.split().str[-1]
    j = jpm[jpm["date"] >= pd.Timestamp(start)]
    m = f.merge(j[["date", "speaker", "hawk_dove_score"]],
                left_on=["date", "surname"], right_on=["date", "speaker"], how="inner")
    if len(m) < 30:
        return {"matched": int(len(m)), "note": "too few matched speeches"}
    out = {"matched": int(len(m)), "n_fedlock": int(len(f)), "n_jpm": int(len(j))}
    for c in ("m", "ma"):
        out[f"speech_level_{c}"] = {
            "pearson": float(np.corrcoef(m[c], m["hawk_dove_score"])[0, 1]),
            "spearman": float(m[c].corr(m["hawk_dove_score"], method="spearman")),
        }
    return out


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
