"""ZQ-vs-SR3 meeting-probability RV.

Two markets price the same per-meeting move probability P through different
transforms: ZQ through its means (the FedWatch ladder), SR3 options through
their variance and node CDF (parity pins their mean to the SR3 future, so the
mean channel is dead by construction and everything here is shape).

See ``docs/superpowers/specs/2026-07-30-zq-sr3-meeting-prob-design.md``.

Modules
-------
``ladder``   ZQ settles -> per-meeting jump lattices, with staleness gates.
``atoms``    the settlement transform -> mean-pinned atom distribution at expiry.
``pricer``   closed-form listed-structure pricing over smeared atoms.
``refit``    mantissa refit to listed premiums + the half-tick bootstrap.
``monitor``  channel decomposition and the two-digital classifier.
"""
from RVUtils.MeetingProb.atoms import (
    ContractMeetings,
    ResolvedMeeting,
    atom_distribution,
    split_meetings,
)
from RVUtils.MeetingProb.ladder import (
    MeetingLattice,
    ladder_history,
    meeting_ladder,
    zq_settle_panel,
)
from RVUtils.MeetingProb.monitor import boundary_digitals, channel_row, two_digital_test
from RVUtils.MeetingProb.pricer import (
    digital_prob,
    event_std_bp,
    price_option,
    price_vertical,
)
from RVUtils.MeetingProb.refit import (
    HALF_TICK_BP,
    RefitResult,
    bootstrap_refit,
    refit_lattice,
    select_quotes,
)

__all__ = [
    "HALF_TICK_BP",
    "ContractMeetings", "MeetingLattice", "RefitResult", "ResolvedMeeting",
    "atom_distribution", "boundary_digitals", "bootstrap_refit", "channel_row",
    "digital_prob", "event_std_bp", "ladder_history", "meeting_ladder",
    "price_option", "price_vertical", "refit_lattice", "select_quotes",
    "split_meetings", "two_digital_test", "zq_settle_panel",
]
