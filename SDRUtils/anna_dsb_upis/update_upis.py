# ABOUTME: ANNA-DSB UPI download script for updating local reference data.
# ABOUTME: Fetches latest swap/swaption/cap UPI CSV files using bearer token authentication.

import os
import sys

sys.path.append("../../../")

from anna_dsb_upis.utils import AnnaDSBFetcher

if __name__ == "__main__":

    dir_path = os.path.dirname(os.path.realpath(__file__))

    anna_dsb_fetcher = AnnaDSBFetcher()

    bearer_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImN4WExKNEZ5UVAxdnl0dEtGX1g5dCJ9.eyJodHRwczovL3Byb2QuYW5uYS1kc2IuY29tL3VzZXJuYW1lIjoic2luYXBpNDg3OEBjdWNhZGFzLmNvbSIsImh0dHBzOi8vcHJvZC5hbm5hLWRzYi5jb20vZmRsVDBBY2Nlc3NVUEkiOmZhbHNlLCJodHRwczovL3Byb2QuYW5uYS1kc2IuY29tL3NlYXJjaExpbWl0VVBJIjo1LCJodHRwczovL3Byb2QuYW5uYS1kc2IuY29tL2dyb3VwSWRzIjpbIjIwLjEyMDAuMS9VUElfUmVhZCJdLCJpc3MiOiJodHRwczovL2F1dGguYW5uYS1kc2IuY29tLyIsInN1YiI6ImF1dGgwfDY5NWU0Zjc1Y2QwY2IyOWEyNTJiZDdkYiIsImF1ZCI6WyJndWkiLCJodHRwczovL2NmLWFubmEtZHNiLmV1LmF1dGgwLmNvbS91c2VyaW5mbyJdLCJpYXQiOjE3Njc3OTYwNDYsImV4cCI6MTc2Nzc5Njk0Niwic2NvcGUiOiJvcGVuaWQgcHJvZmlsZSBlbWFpbCBvZmZsaW5lX2FjY2VzcyIsImF6cCI6Ikg3SEVMdVhBakZMSFJ0NW5aanJhMklZdmZKYzRHb1NFIn0.NRj5gCDRSYQM-owuMkQO_hU7ZTGfegFqnRQQ2PIrZSWqHWYWwQbgp6WVwdx4qmPK9D0EjnIgBqPzTNfrWvYVF8t8Wf5oUl3majn7SyvHnu5t2oe2MEo0UbDn8KaPx6MNAUaZARPN8fLclv1SIXSaiQW3a7_x8YuN6FqVYjYRMMoaqSmgyLue5aBZyVm2LYobHMV-AWuBsiY8wbtvFKvWk5Tyl6ufoL1sDhqBbBwO7a7pChWdqVqNBhv7dcpS10_5aum02OhBUEU6_aPb1iGn_PnMuFIVynXReutJfa8iAB8rNE3UueKdllWONE3ZK6bJwqb8QGtWzHdJYQv4LBGGww" 

    default_files = [
        # "Rates-Option-Swaption.csv",
        # "Rates-Swap-Fixed_Float_OIS.csv",
        # "Rates-Swap-Fixed_Float.csv",
        # "Rates-Swap-Cross_Currency_Basis.csv",
        # "Rates-Swap-Basis.csv",
        # "Rates-Swap-Basis_OIS.csv",
        "Rates-Swap-Non_Standard.csv",
        "Rates-Swap-Inflation_Basis.csv"
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
