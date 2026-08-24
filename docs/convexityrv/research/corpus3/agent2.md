# Coverage of A (`convexityrv_markdown`) by B (`corpus2`)

## Match rate — measured, staged

| Stage | Method | Result |
|---|---|---|
| 0 | Files enumerated in A (`ls -A`; all `.md`, no subdirs, no dotfiles) | **97** |
| 1 | Exact basename found verbatim in B (`grep -rF`) | **64 / 97** |
| 2 | + distinctive title-token match for the 33 residuals (26 probes, all HIT) | **92 / 97** |
| 3 | + byte-identity (`md5sum`) resolution of the last 5 | **97 / 97 (100%)** |
| — | Distinct documents in A after dedup (88 unique md5s across 97 files) | **88 / 88 covered (100%)** |

Every one of the 97 was individually checked; none was assumed.

## Uncovered documents: **none**

The 5 files that survived stages 1–2 are not new documents — they are byte-identical copies of files B extracts in full:

| A file (stage-2 miss) | md5 | Identical to | Covered at |
|---|---|---|---|
| `print (4).pdf.md`, `print (16).pdf.md` | `675583ae…` | `print (12).pdf.md` | `g10-print-files.md` §4 — Citi *NA Rates Trade Idea*, "Sell Blues convexity adjustments, hedged" (09 Feb 2017) |
| `print (5).pdf.md`, `print (7).pdf.md` | `1df2136f…` | `print (15).pdf.md` | `g10-print-files.md` §8 — Citi *US Rates Weekly*, "Swearing in huge expectations" (13 Jan 2017) |
| `print (6).pdf.md` | `795ab54e…` | `print (14).pdf.md` | `g10-print-files.md` §9 — Citi *US Rates Vol Lab*, "Buy long expiries" (17 Jan 2017) |

The remaining 4 duplicate clusters in A (`Turning Green from Blue`, `For cheap gamma`, `Forward_steepener_and_vol_divergence`, `Trading long-dated convexity` — each a `(1)` copy) were already covered at stage 1 or 2.

Because the uncovered set is empty, the title/publisher/date/bullets/verdict template applies to nothing. I have not padded it onto the duplicates.

## Verification notes

- **Not bare mentions.** Each of the 64 stage-1 hits was mapped to its nearest preceding heading in B; all 64 land inside a real `## N.` document section (or a whole-file `#` header for the two book-length sources, `g04` Huggins & Schaller and `g05` Aikin). No hit was a passing reference in a cross-corpus list.
- **B's section inventory:** 112 numbered doc sections across g01–g11 — more than 88 because `g08` splits the dated Citi Vol Lab franchise and `g06` adds a synthesis section.
- **Near-duplicate trap checked and clean.** `20y10y_flatteners.pdf.md` and `20y10y_flatteners (1).pdf.md` are *not* duplicates (05 Dec 2019 "Taking profits" vs 16 Oct 2019 "Reweighting"). B covers both separately at `g08-citi-vol-lab.md` §13 and §12, and explicitly flags the distinction at `g08:510` ("distinct document from #12 (close-out vs reweight), not a duplicate").
- **No skip/deferral language** anywhere in B indicating a document was catalogued but abandoned.

## One caveat on coverage *depth* (not coverage)

`pm_bbgchat.txt.md` is the only item in A that was never substantively extracted. B indexes it at `g01-stir-ca-core.md` §9 and in the doc table as *"Long-end 10y10y/20y10y 'strikeless vol' — NOT STIR CA; one-line summary only."* That is coverage by deliberate triage decision, not by extraction. If you want the long-end strikeless-vol chat mined for the vol-proxy leg, it is the one file to revisit — but it was dismissed on purpose, not missed.

The two `Citi Velocity*.pdf.md` sales notes carry a similar LOW-relevance tag but do have real extracted sections (`g11` §4 and §5) with tie-out levels, so they are genuinely covered.

## Bearing on the thesis

No new reading was required, so nothing new bears on *"trade the SOFR futures CA (gamma) against an IMM-dated USD SOFR swap butterfly (linear-space vol proxy), sized gamma-vs-vega."* Worth flagging that the three duplicate clusters are precisely the **Citi Bikbov/Williams Jan–Feb 2017 "sell Blues CA hedged with a 2s5s10s swap fly"** sequence — the closest published precedent for the exact structure in the thesis, and already extracted at `g10` §4/§8/§9. The duplication is an artifact of the PDF collection pass, not a gap.