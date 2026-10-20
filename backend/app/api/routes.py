from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..agent.budget import Bundle, build_bundles
from ..agent.preferences import Preferences, parse_goal
from ..agent.recommender import recommend
from ..agent.workflow import Session, SessionStore, Stage
from ..catalog.models import Category, Garment
from ..catalog.repository import Catalog
from ..config import Settings, get_settings
from ..deps import get_catalog, get_jobs, get_session, get_store, get_youcam
from ..jobs import Job, JobRunner
from ..media.validation import ImageKind, ImageRejected, normalize_exif, validate_image
from ..youcam import YouCamClient
from ..youcam.skin import analyze_skin
from ..youcam.vto import PREVIEW_DISCLAIMER, GarmentCategory, try_on_garment

router = APIRouter(prefix="/api")

SKIN_NOTE = (
    "Cosmetic image analysis, not a medical diagnosis. Results depend on lighting, "
    "camera quality and pose. See a clinician for any skin health concern."
)


class GoalIn(BaseModel):
    text: str


async def _read_image(upload: UploadFile, kind: ImageKind, settings: Settings):
    raw = await upload.read(settings.max_upload_mb * 1024 * 1024 + 1)
    try:
        v = validate_image(raw, kind, settings.max_upload_mb)
    except ImageRejected as exc:
        raise HTTPException(422, {"message": str(exc), "code": exc.code}) from None
    return v, normalize_exif(v.data)


def _session_view(s: Session) -> dict:
    return {
        "id": s.id,
        "stage": s.stage,
        "prefs": s.prefs,
        "skin": s.skin,
        "tryons": {k: v for k, v in s.tryons.items()},
        "consent": {"face": s.consent_face, "body": s.consent_body},
        "skin_note": SKIN_NOTE,
        "preview_note": PREVIEW_DISCLAIMER,
    }


@router.get("/health")
async def health(settings: Settings = Depends(get_settings), catalog: Catalog = Depends(get_catalog)):
    return {
        "ok": True,
        "youcam_configured": bool(settings.youcam_api_key),
        "catalog_is_sample": catalog.is_sample,
        "catalog_notice": catalog.notice,
    }


@router.post("/sessions")
async def create_session(store: SessionStore = Depends(get_store)):
    s = store.create()
    s.log("session_started")
    return _session_view(s)


@router.get("/sessions/{session_id}")
async def read_session(s: Session = Depends(get_session)):
    return _session_view(s)


@router.post("/sessions/{session_id}/goal")
async def set_goal(body: GoalIn, s: Session = Depends(get_session)):
    if not body.text.strip():
        raise HTTPException(422, "Tell us what you're shopping for.")
    s.prefs = parse_goal(body.text[:1000])
    s.log("goal_set", fragrance_free=s.prefs.fragrance_free, has_budget=s.prefs.budget is not None)
    return {"prefs": s.prefs}


@router.put("/sessions/{session_id}/prefs")
async def edit_prefs(prefs: Preferences, s: Session = Depends(get_session)):
    """The shopper can correct anything the parser extracted."""
    s.prefs = prefs
    return {"prefs": s.prefs}


@router.post("/sessions/{session_id}/skin")
async def start_skin_analysis(
    image: UploadFile = File(...),
    consent: bool = Form(False),
    analysis_mode: str = Form("upload"),
    capture_source: str = Form("file"),
    s: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    client: YouCamClient = Depends(get_youcam),
    jobs: JobRunner = Depends(get_jobs),
) -> dict:
    if not consent:
        raise HTTPException(422, {"message": "Consent is required to analyze a face photo.", "code": "consent_required"})
    v, clean = await _read_image(image, ImageKind.face, settings)
    s.consent_face = True
    s.go(Stage.skin_running)
    s.log("skin_started", analysis_mode=analysis_mode, capture_source=capture_source)

    async def run():
        try:
            report = await analyze_skin(
                client,
                clean,
                v.content_type,
                extra_params={"analysis_mode": analysis_mode, "capture_source": capture_source},
            )
        except Exception:
            s.stage = Stage.intake if s.skin is None else Stage.skin_done
            s.log("skin_failed")
            raise
        s.skin = report
        s.go(Stage.skin_done)
        s.log("skin_done", concerns=len(report.concerns))
        return report

    job = jobs.submit("skin", run)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
async def read_job(job_id: str, jobs: JobRunner = Depends(get_jobs)) -> Job:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@router.get("/catalog/products")
async def list_products(catalog: Catalog = Depends(get_catalog)):
    return {"products": catalog.products, "sample": catalog.is_sample}


@router.get("/catalog/products/{product_id}")
async def get_product(product_id: str, catalog: Catalog = Depends(get_catalog)):
    product = catalog.product(product_id)
    if product is None:
        raise HTTPException(404, "Unknown product.")
    return product


@router.get("/catalog/garments")
async def list_garments(catalog: Catalog = Depends(get_catalog)):
    return {"garments": catalog.garments, "sample": catalog.is_sample}


def _recs_payload(s: Session, catalog: Catalog) -> dict:
    prefs = s.prefs or Preferences()
    ranked = recommend(catalog, prefs, s.skin)
    return {
        "ranked": {c.value: r for c, r in ranked.items()},
        "has_analysis": s.skin is not None,
        "catalog_is_sample": catalog.is_sample,
    }


@router.get("/sessions/{session_id}/recommendations")
async def recommendations(s: Session = Depends(get_session), catalog: Catalog = Depends(get_catalog)):
    payload = _recs_payload(s, catalog)
    if s.stage is Stage.skin_done:
        s.go(Stage.recommended)
    s.log("recs_viewed")
    return payload


@router.post("/sessions/{session_id}/tryon")
async def start_tryon(
    person: UploadFile = File(...),
    consent: bool = Form(False),
    garment_id: str | None = Form(None),
    garment_url: str | None = Form(None),
    garment_image: UploadFile | None = File(None),
    category: GarmentCategory = Form(GarmentCategory.auto),
    s: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    client: YouCamClient = Depends(get_youcam),
    catalog: Catalog = Depends(get_catalog),
    jobs: JobRunner = Depends(get_jobs),
) -> dict:
    if not consent:
        raise HTTPException(422, {"message": "Consent is required to process a body photo.", "code": "consent_required"})

    key = garment_id or "custom"
    g_url: str | None = None
    if garment_id:
        g = catalog.garment(garment_id)
        if g is None:
            raise HTTPException(404, "Unknown garment.")
        category = GarmentCategory(g.category)
        g_url = g.image_url
    if garment_url:
        if not garment_url.lower().startswith("https://"):
            raise HTTPException(422, "Garment URL must be https.")
        g_url = garment_url

    g_img = None
    if garment_image is not None and garment_image.filename:
        g_img = await _read_image(garment_image, ImageKind.garment, settings)
        g_url = None  # an uploaded image wins over a URL
    if g_url is None and g_img is None:
        raise HTTPException(
            422,
            {"message": "This garment has no product image yet. Upload a product photo or paste an https image URL.",
             "code": "garment_image_required"},
        )

    pv, p_clean = await _read_image(person, ImageKind.body, settings)
    s.consent_body = True
    s.go(Stage.tryon_running)
    s.selected_garment = key
    s.log("tryon_started", garment=key)

    async def run():
        try:
            result = await try_on_garment(
                client,
                person_image=p_clean,
                person_content_type=pv.content_type,
                garment_image=g_img[1] if g_img else None,
                garment_content_type=g_img[0].content_type if g_img else None,
                garment_url=g_url,
                category=category,
            )
        except Exception:
            s.stage = Stage.recommended
            s.log("tryon_failed", garment=key)
            raise
        s.tryons[key] = result
        s.go(Stage.recommended)
        s.log("tryon_done", garment=key)
        return result

    job = jobs.submit("tryon", run)
    return {"job_id": job.id}


class PlanOut(BaseModel):
    prefs: Preferences
    bundles: list[Bundle]
    garment: Garment | None
    tryon_url: str | None
    notes: list[str]


@router.get("/sessions/{session_id}/plan")
async def plan(
    garment_id: str | None = None,
    s: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
) -> PlanOut:
    prefs = s.prefs or Preferences()
    garment = catalog.garment(garment_id) if garment_id else None
    if garment_id and garment is None:
        raise HTTPException(404, "Unknown garment.")
    ranked = recommend(catalog, prefs, s.skin)
    bundles = build_bundles(ranked, garment, prefs.budget)
    notes = [SKIN_NOTE, PREVIEW_DISCLAIMER]
    if catalog.is_sample:
        notes.append("Product data in this build is sample data, not real retailer listings.")
    if not bundles:
        notes.append("No products met your constraints. Try relaxing one, or check missing ingredient lists.")
    tryon = s.tryons.get(garment_id or "custom")
    s.go(Stage.planned)
    s.log("plan_viewed", bundles=len(bundles))
    return PlanOut(prefs=prefs, bundles=bundles, garment=garment,
                   tryon_url=tryon.image_url if tryon else None, notes=notes)


@router.delete("/sessions/{session_id}/data")
async def delete_data(s: Session = Depends(get_session)):
    """Consent withdrawal. We never write photos to disk; this drops derived results."""
    s.wipe_images_and_results()
    return {"deleted": True}


@router.get("/sessions/{session_id}/events")
async def events(s: Session = Depends(get_session)):
    return {"events": s.events}


__all__ = ["router", "Category"]
