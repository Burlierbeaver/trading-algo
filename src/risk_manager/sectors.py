from __future__ import annotations

import json
from pathlib import Path


UNKNOWN_SECTOR = "UNKNOWN"


class SectorClassifier:
    """Maps symbols to sectors from a JSON dictionary."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._map = {k.upper(): v for k, v in mapping.items()}

    @classmethod
    def from_file(cls, path: str | Path) -> "SectorClassifier":
        p = Path(path)
        if not p.exists():
            return cls({})
        with open(p) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"sector mapping at {p} must be an object")
        return cls(data)

    def sector_of(self, symbol: str) -> str:
        return self._map.get(symbol.upper(), UNKNOWN_SECTOR)

    def known(self, symbol: str) -> bool:
        return symbol.upper() in self._map
