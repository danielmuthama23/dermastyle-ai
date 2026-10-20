import asyncio
from pathlib import Path

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.deps import get_jobs, get_store, get_youcam
from app.main import create_app
from app.agent.workflow import SessionStore
from app.jobs import JobRunner
from app.youcam import YouCamClient

from .conftest import BASE, S3, file_api_ok, jpeg, make_settings, no_sleep
from .test_youcam_client import SKIN_OK



@pytest.fixture
async def api():
    app = create_app()
    yc_http = httpx.AsyncClient()
    yc = YouCamClient(make_settings(), http=yc_http, sleep=no_sleep)
    store, jobs = SessionStore(), JobRunner()
    app.dependency_overrides[get_youcam] = lambda: yc
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_jobs] = lambda: jobs
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await yc_http.aclose()


async def wait_job(api, job_id):
    for _ in range(100):
        j = (await api.get(f"/api/jobs/{job_id}")).json()
        if j["state"] != "running":
            return j
        await asyncio.sleep(0.01)
    raise AssertionError("job never finished")


async def new_session(api) -> str:
    return (await api.post("/api/sessions")).json()["id"]


@respx.mock(assert_all_called=False)
async def test_skin_requires_consent(api):
    sid = await new_session(api)
    r = await api.post(f"/api/sessions/{sid}/skin", files={"image": ("a.jpg", jpeg(), "image/jpeg")}, data={"consent": "false"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "consent_required"


@respx.mock(assert_all_called=False)
async def test_bad_image_rejected_before_any_api_call(api):
    sid = await new_session(api)
    route = respx.post(f"{BASE}/s2s/v2.0/file")
    r = await api.post(f"/api/sessions/{sid}/skin", files={"image": ("a.jpg", jpeg(200, 200), "image/jpeg")}, data={"consent": "true"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_small"
    assert not route.called


@respx.mock
async def test_full_journey_with_mocked_youcam(api):
    respx.post(f"{BASE}/s2s/v2.0/file").mock(return_value=file_api_ok())
    respx.put(S3).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE}/s2s/v2.0/task/skin-analysis").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"task_id": "S"}}))
    respx.get(f"{BASE}/s2s/v2.0/task/skin-analysis/S").mock(return_value=httpx.Response(200, json=SKIN_OK))
    respx.post(f"{BASE}/s2s/v2.0/task/cloth-v4").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"task_id": "C"}}))
    respx.get(f"{BASE}/s2s/v2.0/task/cloth-v4/C").mock(return_value=httpx.Response(
        200, json={"status": 200, "data": {"task_status": "success", "results": {"url": "https://out/r.png"}}}))

    sid = await new_session(api)
    g = await api.post(f"/api/sessions/{sid}/goal", json={"text": "wedding skincare + elegant outfit under $150, fragrance-free"})
    assert g.json()["prefs"]["budget"] == 150

    r = await api.post(f"/api/sessions/{sid}/skin", files={"image": ("a.jpg", jpeg(), "image/jpeg")}, data={"consent": "true"})
    job = await wait_job(api, r.json()["job_id"])
    assert job["state"] == "done", job

    recs = (await api.get(f"/api/sessions/{sid}/recommendations")).json()
    assert recs["has_analysis"] and recs["catalog_is_sample"]

    # Catalog garments have no product image yet -> must ask for one, not fake it.
    r = await api.post(f"/api/sessions/{sid}/tryon", files={"person": ("p.jpg", jpeg(), "image/jpeg")},
                       data={"consent": "true", "garment_id": "gm-001"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "garment_image_required"

    r = await api.post(f"/api/sessions/{sid}/tryon", files={"person": ("p.jpg", jpeg(), "image/jpeg")},
                       data={"consent": "true", "garment_id": "gm-001", "garment_url": "https://shop.example/dress.png"})
    job = await wait_job(api, r.json()["job_id"])
    assert job["state"] == "done" and job["result"]["image_url"] == "https://out/r.png"

    plan = (await api.get(f"/api/sessions/{sid}/plan", params={"garment_id": "gm-001"})).json()
    assert plan["tryon_url"] == "https://out/r.png"
    assert plan["bundles"] and all(b["total"] <= 150 for b in plan["bundles"] if b["within_budget"])
    assert any("sample data" in n for n in plan["notes"])

    assert (await api.delete(f"/api/sessions/{sid}/data")).json()["deleted"]
    s = (await api.get(f"/api/sessions/{sid}")).json()
    assert s["skin"] is None and s["tryons"] == {}


@respx.mock
async def test_failed_task_gives_shopper_message_not_internals(api):
    respx.post(f"{BASE}/s2s/v2.0/file").mock(return_value=file_api_ok())
    respx.put(S3).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE}/s2s/v2.0/task/skin-analysis").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"task_id": "S"}}))
    respx.get(f"{BASE}/s2s/v2.0/task/skin-analysis/S").mock(return_value=httpx.Response(
        200, json={"status": 200, "data": {"task_status": "error", "error": "error_lighting_dark"}}))
    sid = await new_session(api)
    r = await api.post(f"/api/sessions/{sid}/skin", files={"image": ("a.jpg", jpeg(), "image/jpeg")}, data={"consent": "true"})
    job = await wait_job(api, r.json()["job_id"])
    assert job["state"] == "failed" and "too dark" in job["error"]
    assert (await api.get(f"/api/sessions/{sid}")).json()["stage"] == "intake"


async def test_unknown_session_404(api):
    assert (await api.get("/api/sessions/nope")).status_code == 404


def test_settings_loads_project_root_dotenv(monkeypatch):
    project_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(project_root / "backend")
    monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
    get_settings.cache_clear()
    assert get_settings().youcam_api_key


async def test_health_flags_sample_catalog(api):
    h = (await api.get("/api/health")).json()
    assert h["catalog_is_sample"] is True


async def test_catalog_products_endpoint(api):
    products = (await api.get("/api/catalog/products")).json()
    assert products["sample"] is True
    assert products["products"]
    first = products["products"][0]
    assert first["id"]

    detail = (await api.get(f"/api/catalog/products/{first['id']}"))
    assert detail.status_code == 200
    assert detail.json()["id"] == first["id"]

    missing = await api.get("/api/catalog/products/does-not-exist")
    assert missing.status_code == 404
