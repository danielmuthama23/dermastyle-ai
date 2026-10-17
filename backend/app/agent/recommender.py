"""Transparent skincare ranking.

score = sum over the shopper's weakest concerns of
        (100 - ui_score)/100 * weight, for concerns the product targets.
No concern data (no analysis) -> products are ordered by price only, and the
reason says so. Every reason carries an evidence tag.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from ..catalog.ingredients import Verdict, alcohol_check, fragrance_check
from ..catalog.models import Category, Product
from ..catalog.repository import Catalog
from ..youcam.skin import SkinReport
from .preferences import Preferences


class Evidence(str, Enum):
    measured = "measured"  # returned by YouCam Skin AI
    verified = "verified"  # from catalog data (see provenance.verified)
    catalog = "catalog"  # from catalog data that has not been human-verified
    inferred = "inferred"  # a rule or AI-style inference, not a fact
    unknown = "unknown"  # data missing; shopper should confirm


class Reason(BaseModel):
    text: str
    evidence: Evidence


class Recommendation(BaseModel):
    product: Product
    score: float
    eligible: bool
    reasons: list[Reason]
    warnings: list[Reason] = []
    fragrance: Verdict = Verdict.unknown
    alcohol: Verdict = Verdict.unknown


def _data_tag(p: Product) -> Evidence:
    return Evidence.verified if p.provenance.verified else Evidence.catalog


def evaluate_product(
    product: Product, prefs: Preferences, skin: SkinReport | None, top_concerns: int = 4
) -> Recommendation:
    reasons: list[Reason] = []
    warnings: list[Reason] = []
    eligible = True

    frag, frag_hits = fragrance_check(product.ingredients)
    alc, alc_hits = alcohol_check(product.ingredients)

    if prefs.fragrance_free:
        if frag is Verdict.contains:
            eligible = False
            warnings.append(
                Reason(text=f"Excluded: ingredient list includes {', '.join(frag_hits)}.", evidence=_data_tag(product))
            )
        elif frag is Verdict.unknown:
            eligible = False
            warnings.append(
                Reason(
                    text="Excluded: no ingredient list available, so fragrance-free can't be confirmed.",
                    evidence=Evidence.unknown,
                )
            )
        else:
            reasons.append(
                Reason(text="Published ingredient list has no fragrance terms.", evidence=_data_tag(product))
            )
    if prefs.alcohol_free:
        if alc is Verdict.contains:
            eligible = False
            warnings.append(Reason(text=f"Excluded: contains {', '.join(alc_hits)}.", evidence=_data_tag(product)))
        elif alc is Verdict.unknown:
            eligible = False
            warnings.append(Reason(text="Excluded: ingredient list unavailable.", evidence=Evidence.unknown))

    score = 0.0
    if skin and skin.concerns:
        for c in skin.weakest(top_concerns):
            if c.key in product.targets:
                weight = (100 - c.ui_score) / 100
                score += weight
                reasons.append(
                    Reason(
                        text=f"Targets {c.label.lower()}, which scored {c.ui_score}/100 in your analysis.",
                        evidence=Evidence.measured,
                    )
                )
        if score == 0:
            reasons.append(
                Reason(text="Doesn't target your lowest-scoring areas; included for routine completeness.",
                       evidence=Evidence.inferred)
            )
    else:
        reasons.append(Reason(text="No skin analysis yet, so this is ranked by price only.", evidence=Evidence.inferred))

    if frag is Verdict.contains and not prefs.fragrance_free:
        warnings.append(Reason(text=f"Contains fragrance-related ingredients: {', '.join(frag_hits)}.", evidence=_data_tag(product)))
    if frag is Verdict.unknown and not prefs.fragrance_free:
        warnings.append(Reason(text="Ingredient list unavailable; confirm before buying.", evidence=Evidence.unknown))

    return Recommendation(
        product=product, score=round(score, 4), eligible=eligible, reasons=reasons,
        warnings=warnings, fragrance=frag, alcohol=alc,
    )


def recommend(
    catalog: Catalog, prefs: Preferences, skin: SkinReport | None
) -> dict[Category, list[Recommendation]]:
    cats = prefs.want_categories or list(Category)
    out: dict[Category, list[Recommendation]] = {}
    for cat in cats:
        recs = [evaluate_product(p, prefs, skin) for p in catalog.products if p.category == cat]
        # Eligible first, then by score desc, then cheaper first (deterministic).
        recs.sort(key=lambda r: (not r.eligible, -r.score, r.product.price, r.product.id))
        out[cat] = recs
    return out
