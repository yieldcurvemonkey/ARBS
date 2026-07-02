import pathlib

import pandas as pd
import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def serff_panel() -> pd.DataFrame:
    """Prototype-sample panel (2018-04-02 .. 2026-06-30, contemporaneous).

    Captured from the live public sources on 2026-07-02; regenerate with
    scratch script build_panel_live.py if the sample window changes.
    """
    return pd.read_parquet(FIXTURES / "serff_panel.parquet")
