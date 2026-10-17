"""Ingredient-list analysis with a three-valued result.

A product is only "free" of something if we HAVE an ingredient list and it
contains no matching term. No list means UNKNOWN, never "free".
"""

from __future__ import annotations

import re
from enum import Enum


class Verdict(str, Enum):
    free = "free"
    contains = "contains"
    unknown = "unknown"


# Terms that declare fragrance or are common fragrance components / essential oils.
FRAGRANCE_TERMS = (
    "parfum", "fragrance", "aroma", "perfume",
)
FRAGRANCE_ALLERGENS = (
    "linalool", "limonene", "geraniol", "citronellol", "citral", "eugenol",
    "coumarin", "farnesol", "benzyl salicylate", "benzyl benzoate",
    "cinnamal", "hydroxycitronellal", "amyl cinnamal", "hexyl cinnamal",
    "isoeugenol", "alpha-isomethyl ionone", "butylphenyl methylpropional",
)
ESSENTIAL_OIL_HINTS = (
    "essential oil", "lavandula", "citrus aurantium", "rosa damascena",
    "mentha", "eucalyptus", "cymbopogon", "melaleuca", "pelargonium",
)
ALCOHOL_DENAT = ("alcohol denat", "sd alcohol", "ethanol")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _hits(ingredients: list[str], terms: tuple[str, ...]) -> list[str]:
    found = []
    for ing in ingredients:
        n = _norm(ing)
        if any(t in n for t in terms):
            found.append(ing)
    return found


def fragrance_check(ingredients: list[str] | None) -> tuple[Verdict, list[str]]:
    """Return (verdict, matched ingredient names)."""
    if not ingredients:
        return Verdict.unknown, []
    hits = _hits(ingredients, FRAGRANCE_TERMS + FRAGRANCE_ALLERGENS + ESSENTIAL_OIL_HINTS)
    return (Verdict.contains, hits) if hits else (Verdict.free, [])


def alcohol_check(ingredients: list[str] | None) -> tuple[Verdict, list[str]]:
    if not ingredients:
        return Verdict.unknown, []
    hits = _hits(ingredients, ALCOHOL_DENAT)
    return (Verdict.contains, hits) if hits else (Verdict.free, [])
