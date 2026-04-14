import csv
from collections import Counter

with open('april_fomc_dated_sdr_trades.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    
    # Collect all data
    action_types = Counter()
    event_types = Counter()
    block_trade = Counter()
    package_indicator = Counter()
    package_spread = Counter()
    other_payment_type = Counter()
    other_payment_amt = Counter()
    upi_underlier = Counter()
    platform_ids = Counter()
    fixed_rate_leg1_list = []
    fixed_rate_leg2_list = []
    
    for row in reader:
        action_types[row['Action type']] += 1
        event_types[row['Event type']] += 1
        block_trade[row['Block trade election indicator']] += 1
        package_indicator[row['Package indicator']] += 1
        
        if row['Package transaction spread']:
            package_spread[row['Package transaction spread']] += 1
        if row['Other payment type']:
            other_payment_type[row['Other payment type']] += 1
        if row['Other payment amount']:
            other_payment_amt[row['Other payment amount']] += 1
        if row['UPI Underlier Name']:
            upi_underlier[row['UPI Underlier Name']] += 1
        
        platform_ids[row['Platform identifier']] += 1
        
        if row['Fixed rate-Leg 1'] and row['Fixed rate-Leg 1'] != '':
            try:
                fixed_rate_leg1_list.append(float(row['Fixed rate-Leg 1']))
            except:
                pass
        if row['Fixed rate-Leg 2'] and row['Fixed rate-Leg 2'] != '':
            try:
                fixed_rate_leg2_list.append(float(row['Fixed rate-Leg 2']))
            except:
                pass

print("=" * 80)
print("ACTION TYPE DISTINCT VALUES")
print("=" * 80)
for val, count in action_types.most_common():
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("EVENT TYPE DISTINCT VALUES")
print("=" * 80)
for val, count in event_types.most_common():
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("BLOCK TRADE ELECTION INDICATOR DISTINCT VALUES")
print("=" * 80)
for val, count in block_trade.most_common():
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("PLATFORM IDENTIFIER DISTINCT VALUES (top 15)")
print("=" * 80)
for val, count in platform_ids.most_common(15):
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("PACKAGE INDICATOR DISTINCT VALUES")
print("=" * 80)
for val, count in package_indicator.most_common():
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("PACKAGE TRANSACTION SPREAD (Non-empty values, top 15)")
print("=" * 80)
for val, count in package_spread.most_common(15):
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("OTHER PAYMENT TYPE DISTINCT VALUES (top 15)")
print("=" * 80)
for val, count in other_payment_type.most_common(15):
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("OTHER PAYMENT AMOUNT (Non-empty values, top 15)")
print("=" * 80)
for val, count in other_payment_amt.most_common(15):
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("UPI UNDERLIER NAME (top 20)")
print("=" * 80)
for val, count in upi_underlier.most_common(20):
    print(f"  '{val}': {count}")

print("\n" + "=" * 80)
print("FIXED RATE-LEG 1 ANALYSIS")
print("=" * 80)
print(f"Non-empty values: {len(fixed_rate_leg1_list)}")
if fixed_rate_leg1_list:
    print(f"Min: {min(fixed_rate_leg1_list):.10f}")
    print(f"Max: {max(fixed_rate_leg1_list):.10f}")
    print(f"Mean: {sum(fixed_rate_leg1_list)/len(fixed_rate_leg1_list):.10f}")
    print(f"Sample values (first 10):")
    for v in sorted(set(fixed_rate_leg1_list))[:10]:
        print(f"    {v:.10f}")

print("\n" + "=" * 80)
print("FIXED RATE-LEG 2 ANALYSIS")
print("=" * 80)
print(f"Non-empty values: {len(fixed_rate_leg2_list)}")
if fixed_rate_leg2_list:
    print(f"Min: {min(fixed_rate_leg2_list):.10f}")
    print(f"Max: {max(fixed_rate_leg2_list):.10f}")
    print(f"Mean: {sum(fixed_rate_leg2_list)/len(fixed_rate_leg2_list):.10f}")
    print(f"Sample values (first 10):")
    for v in sorted(set(fixed_rate_leg2_list))[:10]:
        print(f"    {v:.10f}")

# Check for trade_label
with open('april_fomc_dated_sdr_trades.csv', 'r') as f:
    header = f.readline()
    print("\n" + "=" * 80)
    print("TRADE LABEL CHECK")
    print("=" * 80)
    if 'trade_label' in header.lower() or 'Trade label' in header:
        print("✓ trade_label column exists")
    else:
        print("✗ trade_label/Trade label column NOT found")
        
print("\nAll column headers:")
for i, col in enumerate(header.strip().split(','), 1):
    print(f"  {i}. {col}")

