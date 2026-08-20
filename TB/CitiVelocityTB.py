r"""Timeseries builder for the ``CITIVELO`` product, with a tag fast path.

Why this exists
---------------
:class:`~TB.BaseTimeseriesTB.BaseTimeseriesTB` prices every query at every
timestep through ``MDP.get_pricer``. For Citi Velocity that is pathological,
because **most queries are already a tag**: a 10y par rate, a swap spread, a vol
point, a bond yield. Repricing them means stripping a curve at every timestep to
recover a number the add-in already published, and each of those curve builds is a
solver run.

So this builder routes:

* **Fast path** - every leg resolves to a tag and every requested value is the
  published quote. All tags across all such queries are pulled in ONE
  ``CVTSHIST`` sweep of the whole window, and each timestep is then an ``asof``
  slice plus a weighted sum. No curve build, no repricing, no per-timestep COM
  call.
* **Repricing path** - queries with no direct tag (a bootstrapped forward, a
  cube interpolation, a bond metric, anything ``RL_*``/``QL_*``). These go
  through ``get_pricer`` per timestep, exactly as the base class does.

Both are behind one interface, so a notebook never chooses.

Why the equivalence test is not optional
----------------------------------------
A fast path that has not been shown to agree with the path it replaces is a
silent-divergence risk, not an optimisation. :meth:`assert_fast_path_matches` runs
the same structures through both routes and reports the differences, and
``tests/test_citivelo_timeseries.py`` asserts they agree. The comparison is
meaningful because the curve is calibrated to the very quotes the fast path reads:
a 10y par rate repriced off a curve stripped from a grid containing that 10y quote
must reproduce it to solver tolerance (~2e-3 bp at rateslib's default
``func_tol=1e-9``; ~6e-6 bp when it is tightened).

Direct mode
-----------
``direct="live"`` (or ``TimeseriesBuilder(..., direct=...)``) reads straight from
the add-in: no tag cache is read or written, and the request raises rather than
degrading to a cached value. It changes the SHAPE of the result on purpose - a
direct frame is a full grid with explicit ``NaN`` where nothing could be served,
because the alternative is a shorter frame that looks complete. It requires an
MDP built by :meth:`~MDP.CitiVelocityExcel.mdp.CitiVelocityMDP.direct_mdp`, and
that is checked rather than assumed: a "direct" read over a cache-backed reader
would present cached numbers as live, which is the failure the whole mode exists
to prevent. See :mod:`TB.direct_mode`.

Failures are counted and reported, not swallowed
------------------------------------------------
The base class wraps each ``_price_one`` in ``except Exception: continue``, so a
broken query yields a SHORTER frame rather than NaNs and nothing says why.
``IRSwapsTB`` deliberately broke that pattern after a missing-DV01 bug "looked
like no data"; this builder does the same, logging one warning naming the failure
count, the first exception and the affected columns.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

import pandas as pd

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.frequencies import normalise_frequency
from MDP.CitiVelocityExcel.mdp import CitiVelocityMDP
from Query.Base.query_resolution import resolve_for_request, resolve_query
from Query.CitiVelocity._CitiVeloLeg import CitiVeloLeg
from Query.CitiVelocity.CitiVeloQuery import CitiVeloQuery, CitiVeloQueryWrapper
from Query.CitiVelocity.CitiVeloValue import CitiVeloValue, structure_scale
from TB.BaseTimeseriesTB import BaseTimeseriesTB
from TB.direct_mode import DirectMode, parse_direct_mode, resolve_direct_mode
from TB.utils import DateLike

__all__ = ["CitiVelocityTB", "FastPathPlan"]

_logger = logging.getLogger(__name__)


class FastPathPlan:
    """What the router decided, exposed so a caller can see it rather than guess."""

    def __init__(
        self,
        fast: Sequence[CitiVeloQuery],
        slow: Sequence[CitiVeloQuery],
        tags: Sequence[str],
        packages: Mapping[int, Tuple[List[CitiVeloLeg], List[float]]],
        reasons: Mapping[int, str],
    ):
        self.fast = list(fast)
        self.slow = list(slow)
        self.tags = list(tags)
        self.packages = dict(packages)
        self.reasons = dict(reasons)

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"FastPathPlan(fast={len(self.fast)}, slow={len(self.slow)}, tags={len(self.tags)})"
        )

    def summary(self) -> pd.DataFrame:
        """One row per query: which route it took and, for the slow ones, why."""
        rows = []
        for q in self.fast:
            rows.append({"column": q.col_name(), "route": "fast", "reason": "every leg is a tag"})
        for q in self.slow:
            rows.append(
                {"column": q.col_name(), "route": "reprice", "reason": self.reasons.get(id(q), "")}
            )
        return pd.DataFrame(rows)


class CitiVelocityTB(BaseTimeseriesTB):
    """Builds Citi Velocity timeseries, routing tag-resolvable queries to a bulk read.

    >>> tb = CitiVelocityTB(CitiVelocityMDP())                            # doctest: +SKIP
    >>> frame = tb.get_timeseries(date(2024, 1, 1), date(2026, 8, 1),     # doctest: +SKIP
    ...                           [CitiVeloQuery(citi_index="USD_SOFR", tenor="10Y")])
    """

    _DEFAULT_PRICING_MESSAGE = "PRICING CITI VELOCITY TIMESERIES."

    def __init__(
        self,
        mdp: CitiVelocityMDP,
        *,
        date_col: str = "Date",
        show_tqdm: bool = True,
        fast_path: bool = True,
        direct: Union[None, bool, str, DirectMode] = None,
    ):
        super().__init__(mdp, date_col=date_col, show_tqdm=show_tqdm)
        self.mdp: CitiVelocityMDP = mdp
        self.fast_path = bool(fast_path)
        self.direct = parse_direct_mode(direct)

    # -- query handling -------------------------------------------------

    def _flatten_queries(
        self,
        queries: Sequence[Union[CitiVeloQuery, CitiVeloQueryWrapper, List[CitiVeloQuery]]],
    ) -> List[CitiVeloQuery]:
        flat = super()._flatten_queries(queries)
        bad = [q for q in flat if not isinstance(q, CitiVeloQuery)]
        if bad:
            raise TypeError(
                f"CitiVelocityTB only handles CitiVeloQuery, got {type(bad[0]).__name__}. "
                "Route other products through their own TB, or through TimeseriesBuilder."
            )
        return flat

    @staticmethod
    def _citi_frequency(queries: Sequence[CitiVeloQuery]) -> str:
        """The Velocity fetch frequency, which must be the same across a batch.

        This is NOT the reference-point frequency: ``freq='B'`` on
        :meth:`get_timeseries` picks the timesteps, while ``CitiVeloQuery.freq``
        picks the granularity of the underlying ``CVTSHIST`` pull. Mixing MI01 and
        DAILY in one batch would put two different data sets under one frame, so
        it raises.
        """
        freqs = {normalise_frequency(q.freq) for q in queries}
        if len(freqs) > 1:
            raise ValueError(
                f"All queries in one CitiVelocityTB call must share a Velocity frequency, "
                f"got {sorted(freqs)}. Intraday and daily are different data and are cached "
                "under different keys."
            )
        return freqs.pop() if freqs else "DAILY"

    def plan(self, queries: Sequence[CitiVeloQuery]) -> FastPathPlan:
        """Route each query and resolve its package once.

        Leg resolution needs only the catalog, not the market, so it happens here
        rather than per timestep - a Velocity leg spec is complete before any
        snapshot exists.
        """
        resolver = self.mdp.get_pricer({"timestamp": "live"})
        fast: List[CitiVeloQuery] = []
        slow: List[CitiVeloQuery] = []
        tags: List[str] = []
        packages: Dict[int, Tuple[List[CitiVeloLeg], List[float]]] = {}
        reasons: Dict[int, str] = {}

        for q in queries:
            if not self.fast_path:
                slow.append(q)
                reasons[id(q)] = "fast path disabled"
                continue
            if not q.is_quote_only:
                slow.append(q)
                values = q.value if isinstance(q.value, list) else [q.value]
                reasons[id(q)] = (
                    "value is a local reprice: " + ", ".join(getattr(v, "name", str(v)) for v in values)
                )
                continue
            try:
                package, weights = q.resolve_package(pricer_or_curve=resolver, is_for_timeseries=True)
            except Exception as exc:  # noqa: BLE001 - a spec we cannot resolve is not fatal
                slow.append(q)
                reasons[id(q)] = f"leg resolution failed: {exc}"
                continue
            packages[id(q)] = (list(package), [float(w) for w in weights])
            tags.extend(leg.tag for leg in package)
            fast.append(q)

        return FastPathPlan(fast, slow, list(dict.fromkeys(tags)), packages, reasons)

    # -- the public entry point -----------------------------------------

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        queries: List[Union[CitiVeloQuery, List[CitiVeloQuery]]],
        *,
        n_jobs: Optional[int] = 1,
        ignore_cache: Optional[bool] = False,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
        fast_path: Optional[bool] = None,
        direct: Union[None, bool, str, DirectMode] = None,
    ) -> pd.DataFrame:
        """One column per query, indexed by reference point.

        Parameters
        ----------
        freq
            The REFERENCE-POINT frequency (business days by default). The Velocity
            fetch granularity comes from each query's ``freq`` field.
        fast_path
            Overrides the instance default for this call. ``False`` forces every
            query through the repricing path, which is what the equivalence test
            uses to compare the two routes.
        direct
            ``"live"`` / ``True`` reads straight from the add-in: no tag cache is
            read or written, and the request RAISES rather than degrading to a
            cached value if the add-in cannot serve. Requires an MDP built by
            :meth:`~MDP.CitiVelocityExcel.mdp.CitiVelocityMDP.direct_mdp`; it is
            checked, not assumed. Under direct the result is a FULL GRID - one
            row per reference point, one column per query - with an explicit NaN
            wherever no value could be produced, instead of the shorter frame the
            cached path returns.
        """
        assert start <= end, "must have end >= start"
        mode = resolve_direct_mode(direct, self.direct)
        if mode.enabled:
            self._assert_direct_ready(ignore_cache=ignore_cache)

        flat = self._flatten_queries(queries)
        if not flat:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        reference_points = self._build_reference_points(
            start=start, end=end, freq=freq, timestamps=timestamps
        )
        if not reference_points:
            return pd.DataFrame().set_index(pd.Index([], name=self._date_col))

        citi_freq = self._citi_frequency(flat)
        previous = self.fast_path
        if fast_path is not None:
            self.fast_path = bool(fast_path)
        try:
            plan = self.plan(flat)
        finally:
            self.fast_path = previous

        rows: List[Tuple[DateLike, str, float]] = []
        if plan.fast:
            rows.extend(
                self._fast_rows(
                    reference_points=reference_points,
                    plan=plan,
                    citi_freq=citi_freq,
                    ignore_cache=bool(ignore_cache),
                    direct=mode.enabled,
                )
            )
        if plan.slow:
            rows.extend(
                self._reprice_rows(
                    reference_points=reference_points,
                    queries=plan.slow,
                    citi_freq=citi_freq,
                    direct=mode.enabled,
                )
            )
        frame = self._rows_to_frame(rows)
        if mode.enabled:
            self._assert_direct_frame_usable(frame, queries=flat)
        return frame

    # -- direct-mode guards ----------------------------------------------

    def _assert_direct_ready(self, *, ignore_cache: Optional[bool]) -> None:
        """Refuse to CLAIM a direct read this builder cannot actually perform."""
        if not getattr(self.mdp, "direct", False):
            raise CitiVelocityError(
                "CitiVelocityTB was asked for a direct read but its CitiVelocityMDP is "
                "cache-backed, so the values would come from the tag cache while "
                "presenting as live. Build the router over "
                "CitiVelocityMDP(...).direct_mdp(), or drop direct=."
            )
        if ignore_cache:
            raise ValueError(
                "ignore_cache=True is meaningless under direct=. On this path ignore_cache "
                "means REFETCH-AND-PERSIST: it re-reads the tag cache, merges the fetch into "
                "it and serves the merged result, so any timestep the add-in does not serve "
                "keeps its stale cached value. Direct mode reads and writes nothing. Pass "
                "one or the other, not both."
            )

    def _assert_direct_frame_usable(
        self, frame: pd.DataFrame, *, queries: Sequence[CitiVeloQuery]
    ) -> None:
        """An empty or all-NaN direct result must never read as a pass.

        Checked per COLUMN, not per frame: a request for three structures where
        one of them served nothing is the case a frame-level "is it empty?" test
        misses, and it is the one that quietly loses a leg.
        """
        if frame.empty or not len(frame.columns):
            raise CitiVelocityError(
                f"Direct read produced no values at all for {len(queries)} quer(y/ies). "
                "The add-in returned nothing usable over this window. An empty direct "
                "result is not a pass - check the add-in is signed in and the tags and "
                "window are valid."
            )
        dead = [str(c) for c in frame.columns if frame[c].isna().all()]
        if dead:
            raise CitiVelocityError(
                f"Direct read produced no usable value at ANY reference point for "
                f"{len(dead)} column(s): {', '.join(sorted(dead))}. Nothing was served "
                "from cache to paper over it. Check those tags resolve and that the "
                "window is inside their history."
            )

    # -- the fast path --------------------------------------------------

    def _fast_rows(
        self,
        *,
        reference_points: Sequence[DateLike],
        plan: FastPathPlan,
        citi_freq: str,
        ignore_cache: bool = False,
        direct: bool = False,
    ) -> List[Tuple[DateLike, str, float]]:
        """One bulk fetch, then a weighted sum per timestep. No model, no COM loop."""
        if not plan.tags:
            return []

        first = pd.Timestamp(self._to_now(reference_points[0]))
        last = pd.Timestamp(self._to_now(reference_points[-1]))
        # Warm before the window so the first timestep's `asof` has something to
        # resolve against - a window that opens on a holiday otherwise loses row 1.
        lookback = pd.Timedelta(days=7 if citi_freq in {"MI01", "MI10", "HOURLY"} else 45)

        frame = self.mdp.quotes.frame(
            plan.tags,
            citi_freq,
            start=first - lookback,
            end=last,
            # Under direct there is no cache to force past, and passing this
            # would be a lie about what the read does. `strict` instead: a tag
            # the add-in refused must raise naming itself, not vanish into a
            # missing column that looks like "no data here".
            force_refresh=False if direct else ignore_cache,
            strict=direct,
        )
        if frame.empty:
            # Unreachable under direct: `strict=True` above raises first. Kept as
            # the cached path's existing behaviour.
            _logger.warning(
                "CitiVelocityTB fast path: no rows served for %d tag(s) over %s..%s; "
                "those columns are ABSENT from the result, not NaN.",
                len(plan.tags),
                first.date(),
                last.date(),
            )
            return []

        index = frame.index
        rows: List[Tuple[DateLike, str, float]] = []
        missing: Dict[str, int] = {}

        for ref_point in self._iter_reference_points(list(reference_points), plan.fast):
            target = pd.Timestamp(self._to_now(ref_point))
            prior = index[index <= target]
            idx = self._index_value(ref_point)
            if len(prior) == 0:
                if direct:
                    # An explicit NaN, not an absent row: under direct the caller
                    # is told which timesteps the add-in had nothing for, rather
                    # than handed a shorter frame that looks complete.
                    for q in plan.fast:
                        missing[q.col_name()] = missing.get(q.col_name(), 0) + 1
                        rows.append(
                            (idx, self._column_name(q, effective_query=q), float("nan"))
                        )
                continue
            row = frame.loc[prior.max()]
            for q in plan.fast:
                package, weights = plan.packages[id(q)]
                total = 0.0
                complete = True
                for weight, leg in zip(weights, package):
                    value = row.get(leg.tag)
                    if value is None or pd.isna(value):
                        complete = False
                        break
                    total += float(weight) * float(value)
                if not complete:
                    missing[q.col_name()] = missing.get(q.col_name(), 0) + 1
                    if direct:
                        rows.append(
                            (idx, self._column_name(q, effective_query=q), float("nan"))
                        )
                    continue
                total *= structure_scale(package)
                if q.risk_weight is not None:
                    total *= float(q.risk_weight)
                rows.append((idx, self._column_name(q, effective_query=q), float(total)))

        if missing:
            _logger.warning(
                "CitiVelocityTB fast path: %d column(s) had timesteps with an incomplete "
                "package; those rows are %s: %s",
                len(missing),
                "explicit NaN (direct read)" if direct else "ABSENT, not NaN",
                ", ".join(f"{k} ({v} points)" for k, v in sorted(missing.items())),
            )
        return rows

    # -- the repricing path ---------------------------------------------

    def _reprice_rows(
        self,
        *,
        reference_points: Sequence[DateLike],
        queries: Sequence[CitiVeloQuery],
        citi_freq: str,
        direct: bool = False,
    ) -> List[Tuple[DateLike, str, float]]:
        """Build a pricer per timestep and value each query through it.

        Under ``direct`` the quotes reader underneath has no cache, so
        ``bulk_get_data`` DELIVERS the window rather than warming one (see
        :meth:`MDP.CitiVelocityExcel.mdp.CitiVelocityMDP.bulk_get_data`), and
        every (timestep, query) that cannot be produced becomes an explicit NaN
        instead of a silently absent row.
        """
        hint_tags: List[str] = []
        resolver = self.mdp.get_pricer({"timestamp": "live"})
        for q in queries:
            try:
                package, _ = q.resolve_package(pricer_or_curve=resolver, is_for_timeseries=True)
            except Exception:  # noqa: BLE001 - resolution is retried per timestep
                continue
            hint_tags.extend(leg.tag for leg in package)
            for leg in package:
                hint_tags.extend(self._model_input_tags(leg))

        request: Dict[str, Any] = {
            "timestamps": [self._to_now(rp) for rp in reference_points],
            "freq": citi_freq,
            "tags": tuple(dict.fromkeys(hint_tags)),
        }
        pricers = self.mdp.bulk_get_data(request)

        rows: List[Tuple[DateLike, str, float]] = []
        failures = 0
        first_error: Optional[str] = None
        failed_columns: Set[str] = set()
        # Under direct, every (timestep, query) must end up in the frame. The
        # column a query is filed under can differ between its raw and its
        # resolved form, so the name from its first SUCCESS is remembered and
        # reused for its failures - otherwise one query could produce two
        # columns, a real one and an all-NaN twin.
        success_names: Dict[int, str] = {}
        produced: Set[Tuple[Any, int]] = set()

        for ref_point in self._iter_reference_points(list(reference_points), list(queries)):
            now = self._to_now(ref_point)
            pricer = pricers.get(now)
            if pricer is None:
                pricer = self.mdp.get_pricer({"timestamp": now, "freq": citi_freq})
            idx = self._index_value(ref_point)
            for q in queries:
                try:
                    q_resolved = resolve_for_request(q, timestamp=now, pricer_or_curve=pricer)
                    q_eff = resolve_query(q_resolved, timestamp=now, pricer_or_curve=pricer)
                    package, weights = q_eff.resolve_package(
                        pricer_or_curve=pricer, is_for_timeseries=True
                    )
                    vmap = q_eff.build_value_map(
                        pricer_or_curve=pricer, package=package, risk_weights=weights
                    )
                    value_key = getattr(q_eff, "value", None) or q_eff.default_mtm_value_id()
                    value = vmap.apply(value=value_key, **(getattr(q_eff, "value_kwargs", {}) or {}))
                    if q_eff.risk_weight is not None:
                        value = float(value) * float(q_eff.risk_weight)
                    col = self._column_name(q, effective_query=q_eff)
                    success_names.setdefault(id(q), col)
                    produced.add((idx, id(q)))
                    rows.append((idx, col, float(value)))
                except Exception as exc:  # noqa: BLE001 - counted and reported below
                    failures += 1
                    failed_columns.add(q.col_name())
                    if first_error is None:
                        first_error = f"{type(exc).__name__}: {exc}"

        if direct and failures:
            # Fill the holes with explicit NaN so the grid is complete. Done
            # after the loop because a query's column name is only known once
            # it has succeeded somewhere.
            for ref_point in reference_points:
                idx = self._index_value(ref_point)
                for q in queries:
                    if (idx, id(q)) in produced:
                        continue
                    col = success_names.get(id(q)) or self._column_name(q, effective_query=q)
                    rows.append((idx, col, float("nan")))

        if failures:
            _logger.warning(
                "CitiVelocityTB repricing path: %d (timestep, query) pair(s) failed across %d "
                "column(s) [%s]; those rows are %s. First error: %s",
                failures,
                len(failed_columns),
                ", ".join(sorted(failed_columns)),
                "explicit NaN (direct read)" if direct else "ABSENT from the result, not NaN",
                first_error,
            )
        return rows

    @staticmethod
    def _model_input_tags(leg: CitiVeloLeg) -> List[str]:
        """Tags a local model needs beyond the leg's own, so bulk can warm them.

        A par-rate reprice needs the whole par grid, not just the tenor asked for.
        Warming it here is what keeps the repricing path to one ``CVTSHIST`` sweep
        as well.
        """
        from MDP.CitiVelocityExcel import tags as T
        from Query.CitiVelocity._CitiVeloLeg import CitiVeloKind

        if leg.kind in {CitiVeloKind.OIS_PAR, CitiVeloKind.OIS_FWD} and leg.citi_index:
            try:
                return T.ois_par_grid(leg.citi_index)
            except Exception:  # noqa: BLE001 - a hint that cannot be built is not fatal
                return []
        return []

    # -- equivalence ----------------------------------------------------

    def assert_fast_path_matches(
        self,
        start: DateLike,
        end: DateLike,
        queries: Sequence[CitiVeloQuery],
        *,
        model_value: CitiVeloValue = CitiVeloValue.RL_RATE,
        tol: float = 0.01,
        freq: Optional[str] = None,
        timestamps: Optional[List[datetime.datetime]] = None,
        raise_on_breach: bool = True,
    ) -> pd.DataFrame:
        """Run the same structures both ways and report the differences.

        The fast path reads Citi's published quote; the comparison path strips a
        curve from those same quotes and reprices the structure off it. They must
        agree to solver tolerance, and this is what proves the optimisation is an
        optimisation rather than a divergence.

        Parameters
        ----------
        model_value
            The repricing metric to compare against, e.g.
            :attr:`CitiVeloValue.RL_RATE` or :attr:`CitiVeloValue.QL_RATE`.
        tol
            Maximum acceptable absolute difference, in the structures' reporting
            unit (percent for a single-leg rate, basis points for a spread).
        raise_on_breach
            When ``False`` the frame is returned without raising, which is how a
            notebook explores the size of the gap.

        Returns
        -------
        pandas.DataFrame
            Columns ``quote``, ``model``, ``diff``, indexed by
            ``(reference_point, column)``.

        Raises
        ------
        AssertionError
            When any difference exceeds ``tol``.
        ValueError
            When the two paths produce no overlapping points at all - an empty
            comparison must never read as a pass.
        """
        import dataclasses

        quote_queries = [dataclasses.replace(q, value=CitiVeloValue.QUOTE) for q in queries]
        model_queries = [dataclasses.replace(q, value=model_value) for q in queries]

        fast = self.get_timeseries(
            start, end, list(quote_queries), freq=freq, timestamps=timestamps, fast_path=True
        )
        slow = self.get_timeseries(
            start, end, list(model_queries), freq=freq, timestamps=timestamps, fast_path=False
        )

        # Column names carry the value name, so line them up by position in the
        # caller's query list rather than by label.
        pairs = []
        for q_fast, q_model in zip(quote_queries, model_queries):
            col_fast, col_model = q_fast.col_name(), q_model.col_name()
            if col_fast not in fast.columns or col_model not in slow.columns:
                continue
            joined = pd.concat(
                {"quote": fast[col_fast], "model": slow[col_model]}, axis=1
            ).dropna()
            if joined.empty:
                continue
            joined["diff"] = joined["quote"] - joined["model"]
            joined["column"] = col_fast
            pairs.append(joined)

        if not pairs:
            raise ValueError(
                "assert_fast_path_matches produced no overlapping points. An empty comparison is "
                "not a pass - check that the queries resolve and that the window has data."
            )

        out = pd.concat(pairs).set_index("column", append=True)
        worst = float(out["diff"].abs().max())
        if raise_on_breach and worst > tol:
            offenders = (
                out.assign(abs_diff=out["diff"].abs())
                .sort_values("abs_diff", ascending=False)
                .head(5)
            )
            raise AssertionError(
                f"Citi Velocity fast path and repricing path disagree by up to {worst:.6g} "
                f"(tolerance {tol:.6g}). Worst points:\n{offenders}"
            )
        _logger.info(
            "CitiVelocityTB equivalence: %d points, max |diff| = %.6g (tol %.6g)",
            len(out),
            worst,
            tol,
        )
        return out
