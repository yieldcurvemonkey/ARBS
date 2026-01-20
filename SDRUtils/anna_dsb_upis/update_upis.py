# ABOUTME: ANNA-DSB UPI download script for updating local reference data.
# ABOUTME: Fetches latest swap/swaption/cap UPI CSV files using bearer token authentication.

import os
import sys

sys.path.append("../../../")

from anna_dsb_upis.utils import AnnaDSBFetcher

if __name__ == "__main__":

    dir_path = os.path.dirname(os.path.realpath(__file__))

    anna_dsb_fetcher = AnnaDSBFetcher()

    bearer_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImN4WExKNEZ5UVAxdnl0dEtGX1g5dCJ9.eyJodHRwczovL3Byb2QuYW5uYS1kc2IuY29tL3VzZXJuYW1lIjoiamlib2JhYjIyMkBlbGFmYW5zLmNvbSIsImh0dHBzOi8vcHJvZC5hbm5hLWRzYi5jb20vZmRsVDBBY2Nlc3NVUEkiOmZhbHNlLCJodHRwczovL3Byb2QuYW5uYS1kc2IuY29tL3NlYXJjaExpbWl0VVBJIjo1LCJodHRwczovL3Byb2QuYW5uYS1kc2IuY29tL2dyb3VwSWRzIjpbIjIwLjEyMDAuMS9VUElfUmVhZCJdLCJpc3MiOiJodHRwczovL2F1dGguYW5uYS1kc2IuY29tLyIsInN1YiI6ImF1dGgwfDY5NmVhOWVkYWIzNmM2MDRhNjhhYmIzMSIsImF1ZCI6WyJndWkiLCJodHRwczovL2NmLWFubmEtZHNiLmV1LmF1dGgwLmNvbS91c2VyaW5mbyJdLCJpYXQiOjE3Njg4NjQ4MDUsImV4cCI6MTc2ODg2NTcwNSwic2NvcGUiOiJvcGVuaWQgcHJvZmlsZSBlbWFpbCBvZmZsaW5lX2FjY2VzcyIsImF6cCI6Ikg3SEVMdVhBakZMSFJ0NW5aanJhMklZdmZKYzRHb1NFIn0.AyZLOnTQpBciEAtDXibuh9r-txV-KgwsZi6cKrpGKwu1Q0AU79htYRZtENd2QSZCalqEZbVJ58GDUoMg9wA9jF2RD_ICKwf02pWIawZ07e81BWVwJYQUIvKNlvOy2t3nW3cxBN08yGypbbrQTegV7Dkf5jsdXmDkc6oRww3QWwgCTzldwO_UhWAqyle1Y3zw4puehKvWyyfh5tydvJsnA3RHxbKRWi3sKo6ptyv3yqImX4NGPloat0ryhsudLt0-cy_0ypP-8ncw0JXwU3j3tKIeDCSWquHzXllcua4kuU5oZGk_Qo8U9xTWJhBNxJ0gnRHwGDO47E3OKgY5QVS5ZA" 

    default_files = [
        # "Rates-Option-Swaption.csv",
        # "Rates-Swap-Fixed_Float_OIS.csv",
        # "Rates-Swap-Fixed_Float.csv",
        # "Rates-Swap-Cross_Currency_Basis.csv",
        # "Rates-Swap-Basis.csv",
        # "Rates-Swap-Basis_OIS.csv",
        # "Rates-Swap-Non_Standard.csv",
        # "Rates-Swap-Inflation_Basis.csv"

        "Rates-Forward-Debt.csv",
        # "Rates-Option-CapFloor.csv",
        # "Rates-Option-Debt_Option.csv",
    ]
    files = [f for f in os.listdir(".") if os.path.isfile(f)] if len(sys.argv) > 2 and sys.argv[2] == "all" else default_files
    for f in files:
        if ".csv" not in f:
            continue

        print(f"UPDATING {f}")

        anna_dsb_fetcher.update_product_upi_cache(
            product_upi_cache_path=rf"{dir_path}\{f}",
            token=bearer_token,
        )
