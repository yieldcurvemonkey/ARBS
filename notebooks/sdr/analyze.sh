#!/bin/bash

# Extract specific data using proper CSV parsing with a Python one-liner
# Use a simpler approach: count occurrences of key values

echo "=============== FIXED RATE-LEG 1 (Column 47) ==============="
# Extract fixed rate leg 1 values
tail -n +2 april_fomc_dated_sdr_trades.csv | \
awk -F'"' '{for(i=1;i<=NF;i++) if(i%2==1) {split($i,a,","); print a[47]}}' | \
grep -v '^$' | sort -n | uniq -c | tail -20

echo ""
echo "=============== FIXED RATE-LEG 1 RANGE ==============="
tail -n +2 april_fomc_dated_sdr_trades.csv | \
awk -F'"' '{for(i=1;i<=NF;i++) if(i%2==1) {split($i,a,","); if(a[47]!="") print a[47]}}' | \
sort -n | awk 'BEGIN{min=1e10; max=-1e10} {if($1<min) min=$1; if($1>max) max=$1} END{print "Min:", min, "Max:", max}'

