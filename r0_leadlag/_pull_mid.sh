#!/bin/sh
cd "C:/Users/chris/clee/ARBS-r0/r0_leadlag"
for t in 3y 7y 20y; do
  "C:/Users/chris/anaconda3/envs/stir/python.exe" scratch_d1_fullwin.py "$t" 2>&1 | grep -E "minutes in|ERROR|Traceback"
done
echo "MID_DONE"
