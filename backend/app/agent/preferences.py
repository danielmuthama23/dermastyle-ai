"""Deterministic goal parser.

Turns free text such as "wedding next month, under $150, fragrance-free
skincare, elegant outfit" into a structured, editable profile. It is rule
based on purpose: nothing here can invent facts, and every extracted field is
shown to (and editable by) the shopper. An LLM parser can implement the same
`parse_goal` signature later.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..catalog.models import Category

_BUDGET = re.compile(
    r"(?:under|below|less than|max(?:imum)?|up to|within|budget(?: of)?|around|about)?\s*"
    r"(?:\$|usd\s*|us\$\s*)\s?(\d{1,5}(?:[.,]\d{1,2})?)|(\d{1,5})\s*(?:usd|dollars|bucks)",
    re.I,
)
_OCCASIONS = {
    "wedding": ("wedding", "bridal", "bridesmaid"),
    "interview": ("interview",),
    "work": ("office", "work", "business"),
    "party": ("party", "birthday", "celebration", "night out"),
    "holiday": ("holiday", "vacation", "trip", "beach"),
    "date": ("date night", "anniversary"),
}
_STYLE_WORDS = ("elegant", "smart", "formal", "casual", "minimal", "classic", "bold", "relaxed")


class Preferences(BaseModel):
    raw_goal: str = ""
    occasion: str | None = None
    budget: float | None = None
    fragrance_free: bool = False
    alcohol_free: bool = False
    style_tags: list[str] = Field(default_factory=list)
    want_categories: list[Category] = Field(default_factory=list)
    want_outfit: bool = False
    simple_routine: bool = False


def parse_goal(text: str) -> Preferences:
    t = text.lower()
    prefs = Preferences(raw_goal=text.strip())

    for occ, words in _OCCASIONS.items():
        if any(w in t for w in words):
            prefs.occasion = occ
            break

    m = _BUDGET.search(text)
    if m:
        raw = (m.group(1) or m.group(2)).replace(",", ".")
        try:
            prefs.budget = float(raw)
        except ValueError:
            pass

    prefs.fragrance_free = bool(
        re.search(r"fragrance[\s-]*free|unscented|no (?:added )?(?:fragrance|perfume)|without fragrance", t)
    )
    prefs.alcohol_free = bool(re.search(r"alcohol[\s-]*free|no alcohol", t))
    prefs.style_tags = [w for w in _STYLE_WORDS if w in t]
    prefs.simple_routine = bool(re.search(r"\bsimple\b|\bminimal\b|\bbasic\b|few steps|short routine", t))
    prefs.want_outfit = bool(re.search(r"outfit|dress|clothes|clothing|jumpsuit|blouse|shirt|look", t))

    cats: list[Category] = []
    mapping = {
        Category.cleanser: r"cleanser|face wash|wash",
        Category.moisturizer: r"moisturi[sz]er|cream|hydrat",
        Category.sunscreen: r"sunscreen|spf|sun protection",
        Category.serum: r"serum|treatment|brighten",
    }
    for cat, pat in mapping.items():
        if re.search(pat, t):
            cats.append(cat)
    if not cats and re.search(r"skincare|skin care|routine|skin", t):
        cats = [Category.cleanser, Category.moisturizer, Category.sunscreen]
        if not prefs.simple_routine:
            cats.append(Category.serum)
    prefs.want_categories = cats
    return prefs
