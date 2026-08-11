#!/bin/sh
cd "C:/Users/chris/clee/ARBS-r0/r0_leadlag"
for t in 1y 3m 1m 2m 6m; do
  "C:/Users/chris/anaconda3/envs/stir/python.exe" scratch_d1_fullwin.py "$t" 2>&1 | grep -E "minutes in|ERROR|Traceback"
done
echo "SHORT_DONE"
