"""CSV + JSON export of an SFRConvexScreenerSnapshot."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Union

from RVUtils.SFRConvexScreener._types import SFRConvexScreenerSnapshot

logger = logging.getLogger(__name__)


def write_snapshot(
    snapshot: SFRConvexScreenerSnapshot, *, root_dir: Union[str, Path],
) -> Dict[str, Path]:
    root = Path(root_dir) / snapshot.as_of.isoformat()
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "screener_results.csv"
    json_path = root / "screener_results.json"

    df = snapshot.to_dataframe()
    df.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(snapshot.to_dict(), indent=2, default=str))
    logger.info("snapshot written to %s", root)
    return {"csv": csv_path, "json": json_path}
