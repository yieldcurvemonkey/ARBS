from __future__ import annotations

import os

# Default data directory for YCMONKEY SABR parameter files.
# Override via MONKEYCUBE_DATA_DIR environment variable or data_dir kwarg.
_DEFAULT_DATA_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..",
        "project-oasis", "private", "YCMONKEY_USD_VOL_CUBE_GAMMA_MIX",
    )
)


def resolve_data_dir(override: str | None = None) -> str:
    """Resolve the SABR parameter data directory.

    Priority: explicit override > MONKEYCUBE_DATA_DIR env var > default path.
    """
    path = override or os.environ.get("MONKEYCUBE_DATA_DIR") or _DEFAULT_DATA_DIR
    return os.path.normpath(path)
