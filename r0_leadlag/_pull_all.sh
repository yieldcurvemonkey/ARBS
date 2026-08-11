#!/bin/sh
cd "C:/Users/chris/clee/ARBS-r0/r0_leadlag"
for t in 30y 1y 3y 7y 20y 3m 1m 2m 6m; do
  "C:/Users/chris/anaconda3/envs/stir/python.exe" scratch_d1_fullwin.py "$t" 2>&1 \
    | grep -v "Licence\|rateslib is\|^No commercial\|^Any use\|^Certain\|^For licensing\|import rateslib\|from rateslib\|served a snapshot"
done
echo "PULL_ALL_DONE"
