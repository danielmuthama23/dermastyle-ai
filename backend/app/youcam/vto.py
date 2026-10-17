"""YouCam AI Clothes Virtual Try-On (v4) wrapper.

Docs: https://docs.perfectcorp.com/reference/ai_clothes/v4.0
POST /s2s/v2.0/task/cloth-v4 accepts the user image as src_file_id or
src_file_url and the garment as ref_file_id or ref_file_url, plus a required
garment_category.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from .client import YouCamClient
from .errors import YouCamError

FEATURE = "cloth-v4"
PREVIEW_DISCLAIMER = (
    "Visual preview only. It does not guarantee fit, comfort, fabric behavior or final appearance."
)


class GarmentCategory(str, Enum):
    full_body = "full_body"
    upper_body = "upper_body"
    lower_body = "lower_body"
    shoes = "shoes"
    outer = "outer"
    auto = "auto"


class FilterMultiPerson(str, Enum):
    off = "off"
    normal = "normal"
    strict = "strict"


class TryOnResult(BaseModel):
    image_url: str
    garment_category: GarmentCategory
    disclaimer: str = PREVIEW_DISCLAIMER
    source: str = "youcam.cloth-v4"


def build_payload(
    *,
    src_file_id: str | None = None,
    src_file_url: str | None = None,
    ref_file_id: str | None = None,
    ref_file_url: str | None = None,
    category: GarmentCategory = GarmentCategory.auto,
    change_shoes: bool = False,
    filter_multi_person: FilterMultiPerson = FilterMultiPerson.normal,
) -> dict[str, Any]:
    if bool(src_file_id) == bool(src_file_url):
        raise ValueError("provide exactly one of src_file_id or src_file_url")
    if bool(ref_file_id) == bool(ref_file_url):
        raise ValueError("provide exactly one of ref_file_id or ref_file_url")
    payload: dict[str, Any] = {
        "garment_category": category.value,
        "change_shoes": change_shoes,
        "filter_multi_person": filter_multi_person.value,
    }
    if src_file_id:
        payload["src_file_id"] = src_file_id
    else:
        payload["src_file_url"] = src_file_url
    if ref_file_id:
        payload["ref_file_id"] = ref_file_id
    else:
        payload["ref_file_url"] = ref_file_url
    return payload


def parse_tryon_results(data: dict[str, Any], category: GarmentCategory) -> TryOnResult:
    url = (data.get("results") or {}).get("url")
    if not url:
        raise YouCamError("try-on succeeded but returned no result url")
    return TryOnResult(image_url=url, garment_category=category)


async def try_on_garment(
    client: YouCamClient,
    *,
    person_image: bytes,
    person_content_type: str,
    garment_image: bytes | None = None,
    garment_content_type: str | None = None,
    garment_url: str | None = None,
    category: GarmentCategory = GarmentCategory.auto,
) -> TryOnResult:
    """Upload the shopper's photo (and the garment, unless a public URL is given)
    then run the try-on task."""
    src_id = await client.upload_image(person_image, "person.jpg", person_content_type)
    ref_id: str | None = None
    if garment_url is None:
        if garment_image is None or garment_content_type is None:
            raise ValueError("garment_image + garment_content_type or garment_url required")
        ref_id = await client.upload_image(garment_image, "garment.jpg", garment_content_type)
    payload = build_payload(
        src_file_id=src_id, ref_file_id=ref_id, ref_file_url=garment_url, category=category
    )
    data = await client.run_task(FEATURE, payload)
    return parse_tryon_results(data, category)
