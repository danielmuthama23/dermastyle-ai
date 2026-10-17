from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Category(str, Enum):
    cleanser = "cleanser"
    moisturizer = "moisturizer"
    sunscreen = "sunscreen"
    serum = "serum"


class Provenance(BaseModel):
    """Where a product's facts came from. Never leave this blank."""

    source: str  # e.g. "retailer product page", "sample-data"
    url: str | None = None
    retrieved: str | None = None  # ISO date
    verified: bool = False  # True only if a human checked it against the pack/page


class Product(BaseModel):
    id: str
    name: str
    brand: str
    category: Category
    price: float
    currency: str = "USD"
    # None means "ingredient list not available" and must never be read as "empty".
    ingredients: list[str] | None = None
    targets: list[str] = []  # skin concerns the product is positioned for, in YouCam keys
    retailer_url: str | None = None
    provenance: Provenance


class Garment(BaseModel):
    id: str
    name: str
    brand: str
    price: float
    currency: str = "USD"
    category: str  # YouCam garment_category value
    tags: list[str] = []
    image_url: str | None = None  # public product image, required for catalog try-on
    retailer_url: str | None = None
    provenance: Provenance
