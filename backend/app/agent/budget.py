"""Budget-aware bundle selection.

Exhaustive search over the top-N eligible products per category (N small, so
at most N^k combinations). Returns the best-scoring bundle that fits the
budget plus clearly labelled alternatives. If nothing fits, it says by how
much and offers a skincare-only bundle when that fits.
"""

from __future__ import annotations

from itertools import product as cartesian

from pydantic import BaseModel

from ..catalog.models import Category, Garment
from .recommender import Recommendation


class Bundle(BaseModel):
    label: str
    items: list[Recommendation]
    garment: Garment | None
    total: float
    score: float
    within_budget: bool | None  # None when no budget was given


def _make(items: list[Recommendation], garment: Garment | None, budget: float | None, label: str = "") -> Bundle:
    total = round(sum(r.product.price for r in items) + (garment.price if garment else 0.0), 2)
    return Bundle(
        label=label,
        items=items,
        garment=garment,
        total=total,
        score=round(sum(r.score for r in items), 4),
        within_budget=None if budget is None else total <= budget,
    )


def _best_key(b: Bundle) -> tuple:
    return (-b.score, b.total, [r.product.id for r in b.items])


def _enumerate(pools: list[list[Recommendation]], garment: Garment | None, budget: float | None) -> list[Bundle]:
    return [_make(list(combo), garment, budget) for combo in cartesian(*pools)]


def build_bundles(
    ranked: dict[Category, list[Recommendation]],
    garment: Garment | None,
    budget: float | None,
    top_n: int = 4,
) -> list[Bundle]:
    pools = [[r for r in recs if r.eligible][:top_n] for recs in ranked.values()]
    pools = [p for p in pools if p]
    if not pools:
        return []

    candidates = _enumerate(pools, garment, budget)
    fitting = [b for b in candidates if b.within_budget is not False]
    out: list[Bundle] = []

    if fitting:
        best = min(fitting, key=_best_key)
        best.label = "Best match within budget" if budget is not None else "Best match"
        out.append(best)
        cheapest = min(fitting, key=lambda b: (b.total, -b.score))
        if cheapest is not best:
            cheapest.label = "Lowest total"
            out.append(cheapest)
    else:
        closest = min(candidates, key=lambda b: (b.total, -b.score))
        assert budget is not None
        closest.label = f"Closest option: ${closest.total - budget:.2f} over budget"
        out.append(closest)
        if garment is not None:
            bare = [b for b in _enumerate(pools, None, budget) if b.within_budget]
            if bare:
                pick = min(bare, key=_best_key)
                pick.label = "Skincare only (outfit left out to fit your budget)"
                out.append(pick)

    top = min(candidates, key=_best_key)
    if all(top is not b for b in out) and budget is not None and fitting and top.total > budget:
        top.label = f"Best match overall (${top.total - budget:.2f} over budget)"
        out.append(top)
    return out
