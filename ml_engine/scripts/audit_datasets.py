#!/usr/bin/env python3
"""Print a read-only inventory of files under the repository datasets directory."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "datasets"


def inventory_file(path: Path) -> dict[str, object]:
    stat = path.stat()
    entry: dict[str, object] = {
        "path": path.relative_to(ROOT).as_posix(),
        "format": path.suffix.lstrip(".").lower() or "no extension",
        "size_bytes": stat.st_size,
        "last_modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
            timespec="seconds"
        ),
        "row_count": None,
        "columns_and_dtypes": [],
    }
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, low_memory=False)
        entry["row_count"] = len(frame)
        entry["columns_and_dtypes"] = [
            {"column": column, "dtype": str(dtype)}
            for column, dtype in frame.dtypes.items()
        ]
    return entry


def main() -> None:
    files = sorted(path for path in DATASETS.rglob("*") if path.is_file())
    print(json.dumps([inventory_file(path) for path in files], indent=2))


if __name__ == "__main__":
    main()
