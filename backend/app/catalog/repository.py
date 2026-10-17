from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import Garment, Product


class Catalog:
    def __init__(self, products: list[Product], garments: list[Garment], notice: str = "") -> None:
        self.products = products
        self.garments = garments
        self.notice = notice
        self._p = {p.id: p for p in products}
        self._g = {g.id: g for g in garments}

    def product(self, pid: str) -> Product | None:
        return self._p.get(pid)

    def garment(self, gid: str) -> Garment | None:
        return self._g.get(gid)

    @property
    def is_sample(self) -> bool:
        return any(not p.provenance.verified for p in self.products)

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        raw = json.loads(Path(path).read_text())
        return cls(
            [Product(**p) for p in raw["products"]],
            [Garment(**g) for g in raw["garments"]],
            raw.get("_notice", ""),
        )


@lru_cache
def get_catalog(path: str = "data/catalog.json") -> Catalog:
    return Catalog.load(path)
