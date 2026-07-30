"""Configuration for the dealer-ladder signal study.

Frozen dataclasses per concern, bundled by a parent with ``field(default_factory=...)``
— the repo's convention (see ``BT/serff/config.py``). The DEFAULTS ARE THE
PRE-REGISTERED PRIMARY SPECIFICATION, locked 2026-07-29 before any G4 statistic
was computed and written up in
``docs/superpowers/plans/2026-07-30-dealer-ladder-signal-findings.md``. Changing a
default silently changes the primary test, so don't: pass an override instead, and
record it in the trial ledger.
"""
from __future__ import annotations

import dataclasses
import datetime

# ---------------------------------------------------------------- conventions
# Classifier methods, split by whether direction came from a price-vs-mid
# comparison (on-market) or an NPV-vs-upfront inference (off-market).
ON_MARKET_METHODS = ("RATE_VS_MID", "SPREAD_VS_MID", "FLY_VS_MID")
OFF_MARKET_METHODS = ("NPV_VS_UPFRONT",)
# TICK_RULE infers direction from the PREVIOUS reported swap rate rather than
# from a quote, so the audit puts it outside the primary universe entirely.
EXCLUDED_METHODS = ("TICK_RULE",)

# CME roots by bucket space, and their Bloomberg-style prefixes, which are what
# the ladder's bucket_key actually uses (SFRU26, FFN26).
SPACE_ROOT = {"FUTURES": "SR3", "FED_FUNDS": "ZQ"}
SPACE_BBG_PREFIX = {"FUTURES": "SFR", "FED_FUNDS": "FF"}


@dataclasses.dataclass(frozen=True)
class WindowConfig:
    """Realized window and the one-shot lockout.

    Probed 2026-07-29: both ladder curves and the Citi Velocity independent mid
    exist across the whole window, so no shrinkage was needed. 138 trading days,
    split 104 / 34 (6.8 weeks). The lockout is evaluated ONCE — see the burn rule
    in the findings doc.
    """
    start: datetime.date = datetime.date(2026, 1, 12)
    end: datetime.date = datetime.date(2026, 7, 29)
    lockout_start: datetime.date = datetime.date(2026, 6, 10)

    def in_sample(self):
        return self.start, self.lockout_start - datetime.timedelta(days=1)

    def lockout(self):
        return self.lockout_start, self.end


@dataclasses.dataclass(frozen=True)
class UniverseConfig:
    """Which classified prints enter the SIGNED universe.

    ``require_whitelisted_venue`` has to be applied at read time: ``venue_status``
    is not wired into any production path, so both tables contain VENUE_UNKNOWN
    units. It removes ~9.6% of the already-D2C universe and does NOT correct the
    PAID skew (the cleanest stratum still came out ~72% PAID vs ~72.3% overall),
    so treat it as a provenance gate, not a bias fix.
    """
    require_whitelisted_venue: bool = True
    exclude_curve_suspect: bool = True
    methods: tuple = ON_MARKET_METHODS
    directions: tuple = ("PAID", "RECEIVED")
    # Pin the dataset to one pipeline vintage. None = accept whatever is there,
    # which is only safe once the window has been verified single-vintage.
    code_vintage: str | None = None


@dataclasses.dataclass(frozen=True)
class SignalConfig:
    """The ladder-state signal and its standardisation.

    ``weighting="expected"`` is `(1 - 2*p_flip)`. Be aware it is close to inert
    under the current calibration: `disp_jns` is NULL throughout
    `arbs_stir_tick_size_v1`, so `sigma_mid` always falls back to
    `futures_tick_bps/2` and a normal half-spread deviation scores weight ~0.95.
    The expected-vs-unweighted comparison therefore measures the calibration, not
    the signal.
    """
    space: str = "FUTURES"
    half_life_default_min: float = 90.0
    half_life_block_min: float = 240.0
    include_suspect: bool = False
    weighting: str = "expected"
    # standardisation: trailing only, never centred on future data
    z_window_days: int = 10
    # decision grid, ET
    grid_minutes: int = 5
    session_start_hour: int = 8
    session_end_hour: int = 16

    @property
    def half_lives(self) -> dict:
        return {"default": self.half_life_default_min, "block": self.half_life_block_min}


@dataclasses.dataclass(frozen=True)
class CostConfig:
    """Per-CONTRACT cost model.

    Values from ``BT/serff/config.py``; the bp-native per-contract framing follows
    ``RVUtils/MeanRev/contracts.py``, which documents that the older per-LEG charge
    understates a fly (true round trip 2.0bp, not 1.5bp).

    ``ticks_per_leg_per_side = 0.5`` means a round trip costs ONE full tick per
    leg: 0.5bp for a deferred SR3, 0.25bp for one inside its final four months.
    ZQ is charged at its back tick (0.5bp / ~$20.84) throughout, which is the
    conservative choice the feasibility audit asks for even though CME's nearest
    ZQ month does trade in 0.25bp increments. Treat every number here as a LOWER
    BOUND on cost: it excludes slippage, queue loss, legging and impact.
    """
    dv01_per_contract: dict = dataclasses.field(default_factory=lambda: {
        "SR3": 25.0, "ZQ": 41.67, "SR1": 41.67})
    tick_bp_front: dict = dataclasses.field(default_factory=lambda: {
        "SR3": 0.25, "ZQ": 0.50, "SR1": 0.50})
    tick_bp_back: dict = dataclasses.field(default_factory=lambda: {
        "SR3": 0.50, "ZQ": 0.50, "SR1": 0.50})
    ticks_per_leg_per_side: float = 0.5
    front_window_months: int = 4

    def round_trip_bp(self, root: str, *, near_expiry: bool) -> float:
        tick = (self.tick_bp_front if near_expiry else self.tick_bp_back)[root]
        return 2.0 * self.ticks_per_leg_per_side * tick


@dataclasses.dataclass(frozen=True)
class PrimarySpec:
    """The ONE pre-registered test. Pass = mean net > 0 AND raw t >= 3."""
    horizon_min: int = 60
    z_threshold: float = 1.0
    n_contracts: int = 6              # SR3 front 6
    target_space: str = "FUTURES"     # SR3 bench; MEETING may never be a target
    t_pass: float = 3.0
    # positive ladder => dealer long futures-equivalent => must SELL to hedge
    # => predicted RATE RISE. So predicted sign of d(rate) is +sign(ladder).
    predicted_sign: int = +1


@dataclasses.dataclass(frozen=True)
class GridConfig:
    """The secondary family, judged by day-blocked Romano-Wolf at FWER < 0.05."""
    horizons_min: tuple = (5, 15, 30, 60, 240, 1440)
    spaces: tuple = ("FUTURES", "FED_FUNDS", "MEETING")
    half_lives_min: tuple = (30.0, 90.0, 240.0, 1440.0)
    weightings: tuple = ("expected", "unweighted")
    target_spaces: tuple = ("FUTURES", "FED_FUNDS")   # SR3 primary, ZQ cross-check


@dataclasses.dataclass(frozen=True)
class StatsConfig:
    n_boot: int = 2000
    alpha: float = 0.05
    seed: int = 0
    # signed exposure scales by (2a - 1); direction is UNCERTIFIED, so report all
    attenuation_grid: tuple = (0.6, 0.7, 0.8)


@dataclasses.dataclass(frozen=True)
class LadderStudyConfig:
    window: WindowConfig = dataclasses.field(default_factory=WindowConfig)
    universe: UniverseConfig = dataclasses.field(default_factory=UniverseConfig)
    # Off by default so the pre-registered spec is the one that runs unchanged. Turned ON for
    # the robustness re-run, which is where the audit's session-scoped defects are answered:
    # if the verdict is the same with the bad sessions removed, the defects did not drive it.
    session_quality: "session_quality.SessionQualityConfig" = dataclasses.field(
        default_factory=lambda: __import__(
            "BT.dealer_ladder.session_quality", fromlist=["SessionQualityConfig"]
        ).SessionQualityConfig(enabled=False))
    signal: SignalConfig = dataclasses.field(default_factory=SignalConfig)
    cost: CostConfig = dataclasses.field(default_factory=CostConfig)
    primary: PrimarySpec = dataclasses.field(default_factory=PrimarySpec)
    grid: GridConfig = dataclasses.field(default_factory=GridConfig)
    stats: StatsConfig = dataclasses.field(default_factory=StatsConfig)
