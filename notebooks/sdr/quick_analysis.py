import csv
from collections import Counter, defaultdict

# Read CSV
with open('april_fomc_dated_sdr_trades.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    
    # Collect data
    action_types = Counter()
    block_trade = Counter()
    package_indicator = Counter()
    package_spread = Counter()
    other_payment_type = Counter()
    other_payment_amt = Counter()
    upi_underlier = Counter()
    fixed_rate_leg1_vals = []
    fixed_rate_leg2_vals = []
    
    row_count = 0
    for row in reader:
        row_count += 1
        if row_count > 5:
            break
        
        print(f"\n=== ROW {row_count} ===")
        print(f"Action type: '{row['Action type']}'")
        print(f"Event type: '{row['Event type']}'")
        print(f"Platform identifier: '{row['Platform identifier']}'")
        print(f"Block trade election indicator: '{row['Block trade election indicator']}'")
        print(f"UPI Underlier Name: '{row['UPI Underlier Name']}'")
        print(f"Package indicator: '{row['Package indicator']}'")
        print(f"Package transaction spread: '{row['Package transaction spread']}'")
        print(f"Other payment type: '{row['Other payment type']}'")
        print(f"Other payment amount: '{row['Other payment amount']}'")
        print(f"Fixed rate-Leg 1: '{row['Fixed rate-Leg 1']}'")
        print(f"Fixed rate-Leg 2: '{row['Fixed rate-Leg 2']}'")

