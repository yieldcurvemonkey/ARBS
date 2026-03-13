import subprocess
import sys
import time

run_date = "2026-03-12"
underlying_contracts = [
    # "SFRH26",
    "SFRM26",
    "SFRU26",
    "SFRZ26",
    "SFRH27",
    "SFRM27",
    "SFRU27"
    "SFRZ27",
    "SFRH28",
    "SFRM28",
    "SFRU28",
    "SFRZ28",
]

for contract in underlying_contracts:
    try:
        cmd = [
            sys.executable,
            "SDRUtils/_swappulse_scripts/ingest_listed_option_oi_volume.py",
            "once",
            "--date",
            run_date,
            "--underlying-contract",
            contract,
        ]

        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=True)

        # Small pause helps avoid hammering Barchart back-to-back.
        time.sleep(2)
    except:
        continue