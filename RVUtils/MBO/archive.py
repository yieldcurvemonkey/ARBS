"""Finding one session inside the zip archives, without unpacking 64 GB.

Each product's directory holds one or more Databento batch zips, and each zip
holds one ``glbx-mdp3-YYYYMMDD.mbo.dbn.zst`` member per session.  The members are
already zstd-compressed, so the zip stores them without further compression and
pulling one out is a copy rather than a decompression -- 108 MB in 4.7 s,
measured.

A session is extracted to a scratch file rather than streamed into memory.  The
largest SR3 member is 1.6 GB and a pool of workers each holding one decoded
in-memory would not fit in 64 GB; a scratch file costs disk that is already in
the budget, and it lets the decoder seek.

Sessions are keyed by ``(product, date)`` and the index refuses to serve a date
that appears in two zips.  Silently preferring one would make the build
non-deterministic in a way nothing downstream could detect.
"""
from __future__ import annotations

import contextlib
import datetime
import os
import re
import shutil
import zipfile
from typing import Iterator, List, Optional, Sequence

import pandas as pd

from RVUtils.MBO.products import PRODUCTS

__all__ = ["ARCHIVE_ROOTS", "MboArchive", "session_key"]

#: Default layout: one directory per product root, lowercased, beside the others.
ARCHIVE_ROOTS: Sequence[str] = tuple(f"D:/{root.lower()}_mbo" for root in PRODUCTS)

_MEMBER_RE = re.compile(r"glbx-mdp3-(\d{8})\.mbo\.dbn\.zst$")


def _scratch_root() -> str:
    return os.environ.get("ARBS_MBO_SCRATCH", "D:/mbo_work/sessions")


def session_key(product: str, date: datetime.date) -> str:
    """Stable identity for one session, used in logs and manifest rows."""
    return f"{product}/{date.isoformat()}"


class MboArchive:
    """An index over the per-product zip archives."""

    def __init__(self, roots: Optional[Sequence[str]] = None) -> None:
        self.roots = list(roots) if roots is not None else list(ARCHIVE_ROOTS)
        self._sessions: Optional[pd.DataFrame] = None

    # -- index ------------------------------------------------------------- #

    def sessions(self, force: bool = False) -> pd.DataFrame:
        """One row per ``(product, date)``: which zip and member holds it."""
        if self._sessions is not None and not force:
            return self._sessions

        rows: List[dict] = []
        for root in self.roots:
            if not os.path.isdir(root):
                continue
            product = os.path.basename(root.rstrip("/\\")).split("_")[0].upper()
            for fn in sorted(os.listdir(root)):
                if not fn.endswith(".zip"):
                    continue
                zp = os.path.join(root, fn)
                with zipfile.ZipFile(zp) as z:
                    for info in z.infolist():
                        m = _MEMBER_RE.search(info.filename)
                        if not m:
                            continue
                        d = m.group(1)
                        rows.append({
                            "product": product,
                            "date": datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])),
                            "zip_path": zp,
                            "member": info.filename,
                            "member_bytes": int(info.file_size),
                        })

        df = pd.DataFrame(
            rows,
            columns=["product", "date", "zip_path", "member", "member_bytes"],
        )
        if not df.empty:
            dup = df.duplicated(["product", "date"], keep=False)
            if dup.any():
                bad = df[dup].sort_values(["product", "date"])
                raise ValueError(
                    "a session appears in more than one archive, which would make "
                    "the build depend on directory listing order:\n"
                    f"{bad.to_string(index=False)}"
                )
            df = df.sort_values(["product", "date"]).reset_index(drop=True)
        self._sessions = df
        return df

    def products(self) -> List[str]:
        s = self.sessions()
        return [] if s.empty else sorted(s["product"].unique())

    def dates(self, product: str) -> List[datetime.date]:
        s = self.sessions()
        if s.empty:
            return []
        return list(s.loc[s["product"] == product, "date"])

    # -- extraction -------------------------------------------------------- #

    @contextlib.contextmanager
    def open_session(
        self,
        product: str,
        date: datetime.date,
        scratch: Optional[str] = None,
        keep: bool = False,
    ) -> Iterator[str]:
        """Yield a local path to one session's DBN file.

        Re-uses an existing scratch copy whose size already matches, so building
        several tiers of the same session does not extract it twice.  Set
        ``keep`` to leave it in place afterwards.
        """
        s = self.sessions()
        hit = s[(s["product"] == product) & (s["date"] == date)]
        if hit.empty:
            raise KeyError(f"no session {session_key(product, date)} in {self.roots}")
        row = hit.iloc[0]

        out_dir = scratch or _scratch_root()
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"{product}_{os.path.basename(row['member'])}")

        if not os.path.exists(out) or os.path.getsize(out) != int(row["member_bytes"]):
            tmp = f"{out}.{os.getpid()}.part"
            with zipfile.ZipFile(row["zip_path"]) as z, z.open(row["member"]) as src, \
                    open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 24)
            os.replace(tmp, out)

        try:
            yield out
        finally:
            if not keep:
                with contextlib.suppress(OSError):
                    os.remove(out)
