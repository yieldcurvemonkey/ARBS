r"""Safe CVMETADATA probe harness for the Citi Velocity add-in.

Write discipline (both observed AccessViolation crash triggers avoided):
  * never write into or near a live CvFunction_* region -> anchors march down with
    a wide gap and are never reused;
  * never clear or delete a region while the add-in's queued ExcessClr/Format/
    AutoFit actions may be outstanding -> nothing is ever cleared or deleted; the
    workbook is closed once, after a drain pause.

Results are checkpointed to JSON after every batch so a crash cannot lose them.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Iterable

import pythoncom
import win32com.client as win32

PENDING = {-2146826246, -2146826245}
XL_ERR = {
    -2146826288: "#NULL!", -2146826281: "#DIV/0!", -2146826273: "#VALUE!",
    -2146826265: "#REF!", -2146826259: "#NAME?", -2146826252: "#NUM!",
    -2146826246: "#N/A", -2146826245: "#GETTING_DATA",
}
VALUE_ERR = -2146826273
NAME_ERR = -2146826259

MAX_ROW = 900_000
GAP = 30


def show(v):
    return XL_ERR.get(v, v) if isinstance(v, int) else v


# Excel rejects COM calls while it is busy; these are transient, not failures.
BUSY_HRESULTS = {-2147418111, -2147417846}  # RPC_E_CALL_REJECTED, RETRYLATER


def com_retry(fn, attempts: int = 40, delay: float = 0.5):
    """Call fn(), retrying while Excel says 'call rejected by callee'."""
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except AttributeError as exc:
            # While Excel is busy, IDispatch::GetIDsOfNames fails and win32com's
            # dynamic dispatch reports it as AttributeError rather than a COM
            # error - e.g. "Excel.Application.Workbooks" on a perfectly good
            # Application object. Transient, so retry.
            last = exc
            time.sleep(delay)
        except Exception as exc:
            hr = getattr(exc, "hresult", None)
            args = getattr(exc, "args", ())
            code = hr if hr is not None else (args[0] if args else None)
            if code not in BUSY_HRESULTS:
                raise
            last = exc
            time.sleep(delay)
    raise last if last else RuntimeError("com_retry exhausted")


class Prober:
    """Drives CVMETADATA in batches and classifies each tag."""

    @staticmethod
    def _connect():
        """Bind to a USABLE Excel.

        GetActiveObject returns whatever registered in the ROT first, which can be
        a zombie embedded instance with no Workbooks collection. Enumerate and pick
        an instance that actually works and has the add-in's UDFs registered.
        """
        cands = []
        try:
            cands.append(com_retry(lambda: win32.GetActiveObject("Excel.Application")))
        except Exception:
            pass
        try:
            rot = pythoncom.GetRunningObjectTable()
            ctx = pythoncom.CreateBindCtx(0)
            for mk in rot.EnumRunning():
                try:
                    name = mk.GetDisplayName(ctx, None)
                except Exception:
                    continue
                # Do NOT filter on file extension: an unsaved workbook registers
                # as e.g. "Book2", and the zombie instance owns the first slot.
                try:
                    obj = win32.GetObject(name)
                except Exception:
                    continue
                for cand in (getattr(obj, "Application", None), obj):
                    if cand is not None:
                        cands.append(cand)
        except Exception:
            pass

        for app in cands:
            wb = None
            try:
                com_retry(lambda: app.Workbooks.Count)   # zombies fail here
                wb = com_retry(lambda: app.Workbooks.Add())
                ws = wb.Worksheets(1)
                com_retry(lambda: setattr(ws.Range("A1"), "Formula", "=CVTODAY()"))
                if com_retry(lambda: ws.Range("A1").Value) != NAME_ERR:
                    return app, wb, ws
            except Exception:
                pass
            if wb is not None:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass
        raise RuntimeError(
            "No usable Excel with the Citi Velocity add-in signed in. "
            "Open Excel, sign in to Velocity, then retry."
        )

    def __init__(self, checkpoint: pathlib.Path, batch: int = 20, verbose: bool = True):
        pythoncom.CoInitialize()
        self.app, self.wb, self.ws = self._connect()
        self.row = 2 + GAP  # A1 holds the CVTODAY probe; CurrentRegion must not touch it
        self.batch = batch
        self.verbose = verbose
        self.checkpoint = checkpoint
        self.results: dict[str, dict] = {}
        if checkpoint.exists():
            self.results = json.loads(checkpoint.read_text())
            if verbose:
                print(f"resumed {len(self.results)} cached results", flush=True)
        self.calls = 0

    # -- sheet plumbing -------------------------------------------------
    def _anchor(self, rows_needed: int) -> str:
        """Reserve an anchor. rows_needed is only a provisional reservation - the
        cursor is corrected by _advance_past() once the real extent is known,
        because blocks routinely come back far taller than predicted (a 'DAILY 1W'
        request was observed writing 68 rows). Under-reserving would put the next
        anchor inside a live CvFunction_* region, which is a crash trigger.
        """
        if self.row + rows_needed + GAP > MAX_ROW:
            self.ws = self.wb.Worksheets.Add()
            self.row = 1
        cell = f"A{self.row}"
        self.row += rows_needed + GAP
        return cell

    def _advance_past(self, anchor: str, reg) -> None:
        """Push the cursor below the block that was actually written."""
        try:
            bottom = reg.Row + reg.Rows.Count - 1
        except Exception:
            return
        self.row = max(self.row, bottom + 1 + GAP)

    def _settle(self, cell: str, timeout: float = 90.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = self.ws.Range(cell).Value
            pending = v is None or (isinstance(v, int) and v in PENDING) or (
                isinstance(v, str) and ("Requesting" in v or v.startswith("!"))
            )
            if not pending:
                return v
            time.sleep(0.25)
            try:
                self.app.CalculateUntilAsyncQueriesDone()
            except Exception:
                pass
        return "<timeout>"

    # -- one CVMETADATA call --------------------------------------------
    def _call(self, tags: list[str]):
        anchor = self._anchor(len(tags) + 1)
        formula = '=CVMETADATA("{}",TRUE)'.format(",".join(tags))
        self.ws.Range(anchor).Formula = formula
        try:
            self.app.CalculateUntilAsyncQueriesDone()
        except Exception:
            pass
        v = self._settle(anchor)
        self.calls += 1
        if isinstance(v, int) and v in (VALUE_ERR, NAME_ERR):
            return None, show(v)
        reg = self.ws.Range(anchor).CurrentRegion
        self._advance_past(anchor, reg)
        vals = reg.Value
        # normalise to list-of-lists; a 1x1 range comes back as a bare scalar
        if isinstance(vals, tuple):
            rows = [list(r) if isinstance(r, tuple) else [r] for r in vals]
        else:
            rows = [[vals]]
        return rows, None

    @staticmethod
    def _strip_header(rows) -> list:
        if not rows:
            return []
        head = str(rows[0][0]).strip() if rows[0] else ""
        return rows[1:] if head == "Description" else rows

    @staticmethod
    def _classify(desc) -> str:
        """valid | failed | poison.

        The add-in's failure text is context-dependent - the SAME bad tag reads
        'Error: No data available.' when probed alone but 'Error: Invalid Tag /
        No data available. Tag = X' inside a batch that also contains valid tags.
        So 'invalid' vs 'no data' is not a reliable signal and is not split out.
        """
        s = str(desc).strip()
        return "failed" if s.startswith("Error") else "valid"

    def _record(self, tag: str, desc, start=None, end=None, note=None):
        self.results[tag] = {
            "status": self._classify(desc),
            "description": None if desc is None else str(desc),
            "start": str(start) if start is not None else None,
            "end": str(end) if end is not None else None,
            "note": note,
        }

    def probe(self, tags: Iterable[str]) -> dict[str, dict]:
        todo = [t for t in dict.fromkeys(tags) if t not in self.results]
        if self.verbose:
            print(f"probing {len(todo)} new tags (batch={self.batch})", flush=True)
        for i in range(0, len(todo), self.batch):
            chunk = todo[i : i + self.batch]
            self._probe_chunk(chunk)
            self._save()
            if self.verbose:
                done = i + len(chunk)
                nv = sum(1 for t in todo[:done] if self.results.get(t, {}).get("status") == "valid")
                print(f"  {done}/{len(todo)}  valid so far: {nv}  calls={self.calls}", flush=True)
        return {t: self.results[t] for t in tags if t in self.results}

    def _probe_chunk(self, chunk: list[str]):
        rows, err = self._call(chunk)
        if err is not None:
            # a poison tag hard-failed the whole batch -> bisect
            if len(chunk) == 1:
                self._record(chunk[0], f"Error: hard fail {err}", note="poison")
                return
            mid = len(chunk) // 2
            self._probe_chunk(chunk[:mid])
            self._probe_chunk(chunk[mid:])
            return
        # Layout depends on whether ANY tag in the call resolved:
        #   >=1 valid -> row 1 is the header ('Description', 'Start Date', ...)
        #   all failed -> no header at all, error text sits at the anchor
        body = self._strip_header(rows)
        if len(body) != len(chunk):
            # row count mismatch -> fall back to per-tag so nothing is misattributed
            if len(chunk) == 1:
                self._record(chunk[0], "Error: unreadable response", note="mismatch")
                return
            for t in chunk:
                self._probe_chunk([t])
            return
        for tag, cells in zip(chunk, body):
            desc = cells[0] if cells else None
            start = cells[1] if len(cells) > 1 else None
            end = cells[2] if len(cells) > 2 else None
            self._record(tag, desc, start, end)

    # -- authoritative validation via the real data path ----------------
    def probe_tshist(self, tags: list[str], freq: str = "DAILY", period: str = "1W") -> dict:
        """Validate tags with CVTSHIST rather than CVMETADATA.

        CVMETADATA is NOT a sound validator: it returns a hard #VALUE! for tags
        that exist and serve data but carry no metadata (the whole SWAP_SPREAD
        family does this). CVTSHIST is the path we actually fetch through, it
        degrades per column ('Bad tag: <tag>'), and it never poisons a batch.
        """
        out: dict[str, dict] = {}
        todo = [t for t in dict.fromkeys(tags)
                if self.results.get(t, {}).get("via") != "tshist"]
        for t in tags:
            if self.results.get(t, {}).get("via") == "tshist":
                out[t] = self.results[t]
        for i in range(0, len(todo), self.batch):
            chunk = todo[i : i + self.batch]
            anchor = self._anchor(8)
            formula = '=CVTSHIST("{}","{}","{}",,,"CLOSE")'.format(
                ",".join(chunk), freq, period
            )
            self.ws.Range(anchor).Formula = formula
            try:
                self.app.CalculateUntilAsyncQueriesDone()
            except Exception:
                pass
            v = self._settle(anchor)
            self.calls += 1

            if isinstance(v, int) and v in XL_ERR:
                for t in chunk:
                    out[t] = {"status": "failed", "via": "tshist", "note": show(v)}
                continue

            reg = self.ws.Range(anchor).CurrentRegion
            self._advance_past(anchor, reg)
            vals = reg.Value
            if isinstance(vals, tuple):
                rows = [list(r) if isinstance(r, tuple) else [r] for r in vals]
            else:
                rows = [[vals]]
            if len(rows) < 2:
                for t in chunk:
                    out[t] = {"status": "failed", "via": "tshist", "note": "no block"}
                continue

            # Locate the header row by CONTENT, never by index. CurrentRegion
            # absorbs adjacent cells (the A1 readiness probe did exactly this),
            # which shifts every row and made hardcoded rows[1] read the formula
            # row -> every tag misreported as "no column".
            hdr_i = next((i for i, r in enumerate(rows)
                          if r and str(r[0]).strip() == "Date"), None)
            if hdr_i is None:
                for t in chunk:
                    out[t] = {"status": "failed", "via": "tshist", "note": "no header row"}
                self.results.update({k: v2 for k, v2 in out.items() if k in chunk})
                self._save()
                continue
            headers = [str(c) if c is not None else "" for c in rows[hdr_i]]
            first = rows[hdr_i + 1] if len(rows) > hdr_i + 1 else []
            # map by header text, not position
            for t in chunk:
                col = next((j for j, h in enumerate(headers) if h.startswith(t + " ")), None)
                if col is None:
                    out[t] = {"status": "failed", "via": "tshist", "note": "no column"}
                    continue
                cell = first[col] if col < len(first) else None
                if isinstance(cell, str) and cell.startswith("Bad tag"):
                    out[t] = {"status": "failed", "via": "tshist", "note": "bad tag"}
                elif cell is None:
                    out[t] = {"status": "empty", "via": "tshist", "note": "no rows in window"}
                else:
                    out[t] = {"status": "valid", "via": "tshist", "sample": cell,
                              "rows": len(rows) - hdr_i - 1}
            self.results.update({k: v2 for k, v2 in out.items() if k in chunk})
            self._save()
        return out

    def _save(self):
        self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint.write_text(json.dumps(self.results, indent=1, default=str))

    def close(self):
        self._save()
        time.sleep(2.0)  # let queued add-in actions drain before teardown
        try:
            self.wb.Close(SaveChanges=False)
        except Exception as exc:
            print("close failed (excel may have died):", exc, flush=True)
