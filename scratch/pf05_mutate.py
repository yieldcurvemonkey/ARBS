"""Fix probe 5: build mutants of the FIXED probability.py to prove the new
coverage pins can fail. Writes to scratch/_mutfix/, never to SDRUtils/."""
from __future__ import annotations

import os
import pathlib
import sys

SRC = pathlib.Path("C:/Users/chris/clee/ARBS-dd/SDRUtils/dealer_direction/probability.py")
OUT = pathlib.Path("C:/Users/chris/clee/ARBS-dd/scratch/_mutfix")
OUT.mkdir(exist_ok=True)

MUTS = {
    # b0 dropped from the robust fallback -- the b0 100% of real buckets get
    "b0_zero": ("return float(np.median(xt)), h_fb, s_fb, extra",
                "return 0.0, h_fb, s_fb, extra"),
    # the s arm of the second opinion
    "s_arm": ("        s_ind = float(sigma_mid(stats))",
              "        s_ind = 7.0 * float(sigma_mid(stats))"),
    # the fit's own emission of the crosscheck flag
    "xcheck_flag": ("        if xcheck.comparable and not xcheck.agrees:",
                    "        if False:"),
    # pooling on the raw count instead of the usable one
    "raw_n": ("            if fit.n_trimmed < fit.min_n_required and label != GLOBAL_BUCKET:",
              "            if fit.n < fit.min_n_required and label != GLOBAL_BUCKET:"),
    # the donor a pooled fit names
    "donor": ("                fit, bucket=want, pooled_from=label,",
              '                fit, bucket=want, pooled_from="SOMEWHERE_ELSE",'),
    # the label-swap invariance the EM's sign branch rests on
    "swap": ("    z2 = (x - b0 + h) / s", "    z2 = (x - b0 + 2.0 * h) / s"),
    # control: no change at all
    "none": ("MAD_TO_SIGMA = 1.4826", "MAD_TO_SIGMA = 1.4826"),
}

text = SRC.read_text(encoding="utf-8")
for name, (old, new) in MUTS.items():
    if text.count(old) != 1:
        raise SystemExit(f"{name}: anchor found {text.count(old)} times, not once")
    (OUT / f"probability_{name}.py").write_text(text.replace(old, new),
                                                encoding="utf-8")
    print(f"  wrote {name}")
