"""YouCam AI Skin Analysis (SD) wrapper.

Docs: https://docs.perfectcorp.com/reference/ai_skin_analysis
SD and HD concerns cannot be mixed in one request, so this wrapper uses SD only.
Scores: ui_score is a calibrated, motivational 1-100 score; raw_score is the
unadjusted value. Higher means healthier-looking skin for both.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .client import YouCamClient

SD_CONCERNS: tuple[str, ...] = (
    "wrinkle", "droopy_upper_eyelid", "droopy_lower_eyelid", "firmness", "acne",
    "moisture", "eye_bag", "dark_circle_v2", "age_spot", "radiance", "redness",
    "oiliness", "pore", "texture",
)

LABELS: dict[str, str] = {
    "wrinkle": "Wrinkles", "droopy_upper_eyelid": "Upper eyelid", "droopy_lower_eyelid": "Lower eyelid",
    "firmness": "Firmness", "acne": "Blemishes", "moisture": "Moisture", "eye_bag": "Eye bags",
    "dark_circle_v2": "Dark circles", "age_spot": "Age spots", "radiance": "Radiance",
    "redness": "Redness", "oiliness": "Oiliness", "pore": "Pores", "texture": "Texture",
}


class SkinConcern(BaseModel):
    key: str
    label: str
    ui_score: int
    raw_score: float | None = None
    mask_urls: list[str] = []


class SkinReport(BaseModel):
    concerns: list[SkinConcern]
    overall: float | None = None
    skin_age: int | None = None
    source: str = "youcam.skin-analysis"

    def score(self, key: str) -> int | None:
        for c in self.concerns:
            if c.key == key:
                return c.ui_score
        return None

    def weakest(self, n: int = 3) -> list[SkinConcern]:
        """Lowest-scoring concerns first (excluding structural eyelid metrics)."""
        skip = {"droopy_upper_eyelid", "droopy_lower_eyelid"}
        pool = [c for c in self.concerns if c.key not in skip]
        return sorted(pool, key=lambda c: c.ui_score)[:n]


def parse_skin_results(data: dict[str, Any]) -> SkinReport:
    """Parse `data` from a successful task status response (format=json).

    Only values the API returned are surfaced. Entries we don't recognise
    are ignored rather than guessed at.
    """
    results = data.get("results") or {}
    output = results.get("output") or []
    concerns: list[SkinConcern] = []
    overall = None
    skin_age = None
    for item in output:
        key = item.get("type")
        if not key:
            continue
        if key == "all":
            overall = _num(item.get("ui_score") or item.get("score"))
            continue
        if key == "skin_age":
            v = _num(item.get("ui_score") or item.get("score") or item.get("raw_score"))
            skin_age = int(v) if v is not None else None
            continue
        if "ui_score" not in item:
            continue
        concerns.append(
            SkinConcern(
                key=key,
                label=LABELS.get(key, key.replace("_", " ").title()),
                ui_score=int(item["ui_score"]),
                raw_score=_num(item.get("raw_score")),
                mask_urls=list(item.get("mask_urls") or []),
            )
        )
    if overall is None:
        overall = _num((results.get("all") or {}).get("score")) if isinstance(results.get("all"), dict) else None
    if skin_age is None and isinstance(results.get("skin_age"), (int, float)):
        skin_age = int(results["skin_age"])
    return SkinReport(concerns=concerns, overall=overall, skin_age=skin_age)


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


async def analyze_skin(
    client: YouCamClient,
    image: bytes,
    content_type: str,
    file_name: str = "selfie.jpg",
    concerns: tuple[str, ...] = SD_CONCERNS,
    extra_params: dict[str, Any] | None = None,
) -> SkinReport:
    file_id = await client.upload_image(image, file_name, content_type)
    payload: dict[str, Any] = {"src_file_id": file_id, "dst_actions": list(concerns), "format": "json"}
    if extra_params:
        for key, value in extra_params.items():
            if key not in {"src_file_id", "dst_actions", "format"} and value is not None:
                payload[key] = value
    data = await client.run_task("skin-analysis", payload)
    return parse_skin_results(data)
