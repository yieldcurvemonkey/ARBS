# ABOUTME: Diagnostic script to verify central bank meeting dates stored in the cb_events table.
# ABOUTME: Queries database for upcoming Fed, BOC, ECB, and BOE meetings and compares against expected dates.
import psycopg2
from datetime import datetime
import os

# Database connection
DATABASE_URL = "postgresql://postgres.rdobtpugtnmefxplgwyp:0rbZUh8y0Fsvdlry@aws-0-us-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true"

try:
    # Connect to database
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Query for upcoming CB meetings
    query = """
    SELECT currency, event_type, event_date, event_name
    FROM cb_events
    WHERE event_date >= CURRENT_DATE
    AND event_date <= '2025-08-31'
    AND currency IN ('USD', 'CAD', 'EUR', 'GBP')
    ORDER BY currency, event_date
    """
    
    cur.execute(query)
    results = cur.fetchall()
    
    print("\nCURRENT CB MEETING DATES IN DATABASE:\n")
    print(f"{'Currency':<10} {'Type':<10} {'Date':<15} {'Event Name':<50}")
    print('-' * 85)
    
    current_currency = None
    for currency, event_type, event_date, event_name in results:
        if currency \!= current_currency:
            print()  # Add blank line between currencies
            current_currency = currency
        print(f"{currency:<10} {event_type:<10} {event_date.strftime('%Y-%m-%d'):<15} {event_name:<50}")
    
    # Now let's check what the next meeting should be for each
    print("\n\nVERIFICATION - Next meetings should be:")
    print("\nUSD (FOMC): July 30-31, 2025 (decision on July 31)")
    print("CAD (BOC): July 30, 2025")
    print("EUR (ECB): July 31, 2025")
    print("GBP (BOE): August 7, 2025")
    
    print("\nNote: For 2-day meetings, we care about the SECOND day (announcement day)")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
