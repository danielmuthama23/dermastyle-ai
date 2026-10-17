import httpx
import pytest
import respx

from app.youcam import YouCamError, YouCamTaskError, YouCamTimeout
from app.youcam.skin import analyze_skin, parse_skin_results
from app.youcam.vto import GarmentCategory, build_payload, try_on_garment

from .conftest import BASE, S3, file_api_ok, jpeg



@respx.mock
async def test_upload_registers_then_puts_with_server_headers(client):
    reg = respx.post(f"{BASE}/s2s/v2.0/file").mock(return_value=file_api_ok("F9"))
    put = respx.put(S3).mock(return_value=httpx.Response(200))
    fid = await client.upload_image(jpeg(), "a.jpg", "image/jpeg")
    assert fid == "F9"
    assert reg.calls[0].request.headers["authorization"] == "Bearer test-key"
    assert put.calls[0].request.headers.get("authorization") is None  # never leak the key to S3
    assert put.calls[0].request.headers["content-type"] == "image/jpg"


@respx.mock
async def test_upload_rejects_unsupported_type(client):
    with pytest.raises(YouCamError):
        await client.upload_image(b"x", "a.gif", "image/gif")


@respx.mock
async def test_retries_5xx_then_succeeds(client):
    route = respx.post(f"{BASE}/s2s/v2.0/task/skin-analysis").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"status": 200, "data": {"task_id": "T1"}})]
    )
    assert await client.create_task("skin-analysis", {}) == "T1"
    assert route.call_count == 2


@respx.mock
async def test_credit_error_is_not_retried_and_has_user_message(client):
    route = respx.post(f"{BASE}/s2s/v2.0/task/skin-analysis").mock(
        return_value=httpx.Response(400, json={"status": 400, "error": "x", "error_code": "CreditInsufficiency"})
    )
    with pytest.raises(YouCamError) as ei:
        await client.create_task("skin-analysis", {})
    assert route.call_count == 1
    assert ei.value.code == "CreditInsufficiency"
    assert "credits" in ei.value.user_message


@respx.mock
async def test_missing_api_key_fails_cleanly(settings):
    from app.config import Settings
    from app.youcam import YouCamClient
    c = YouCamClient(Settings(youcam_api_key=""), sleep=lambda s: None)
    with pytest.raises(YouCamError) as ei:
        await c.create_task("x", {})
    assert ei.value.code == "InvalidAccessToken"


@respx.mock
async def test_poll_waits_then_returns_success(client):
    respx.get(f"{BASE}/s2s/v2.0/task/cloth-v4/T").mock(side_effect=[
        httpx.Response(200, json={"status": 200, "data": {"task_status": "running"}}),
        httpx.Response(200, json={"status": 200, "data": {"task_status": "success", "results": {"url": "u"}}}),
    ])
    data = await client.poll_task("cloth-v4", "T")
    assert data["results"]["url"] == "u"


@respx.mock
async def test_poll_task_error_surfaces_code(client):
    respx.get(f"{BASE}/s2s/v2.0/task/cloth-v4/T").mock(return_value=httpx.Response(
        200, json={"status": 200, "data": {"task_status": "error", "error": "error_multi_person"}}))
    with pytest.raises(YouCamTaskError) as ei:
        await client.poll_task("cloth-v4", "T")
    assert ei.value.code == "error_multi_person"
    assert "one person" in ei.value.user_message or "more than one" in ei.value.user_message.lower()


@respx.mock
async def test_poll_times_out(client):
    respx.get(f"{BASE}/s2s/v2.0/task/skin-analysis/T").mock(return_value=httpx.Response(
        200, json={"status": 200, "data": {"task_status": "running"}}))
    # deadline 1.0s with 0 delay never advances `waited`; make deadline 0
    client._s.youcam_poll_deadline_s = 0.0
    with pytest.raises(YouCamTimeout):
        await client.poll_task("skin-analysis", "T")


SKIN_OK = {"status": 200, "data": {"task_status": "success", "results": {"output": [
    {"type": "moisture", "ui_score": 52, "raw_score": 41.2, "mask_urls": ["m1"]},
    {"type": "pore", "ui_score": 84, "raw_score": 88.4, "mask_urls": []},
    {"type": "oiliness", "ui_score": 61, "raw_score": 55.0, "mask_urls": []},
]}}}


def test_parse_skin_results_only_uses_returned_values():
    rep = parse_skin_results(SKIN_OK["data"])
    assert [c.key for c in rep.concerns] == ["moisture", "pore", "oiliness"]
    assert rep.overall is None and rep.skin_age is None  # not invented
    assert [c.key for c in rep.weakest(2)] == ["moisture", "oiliness"]


@respx.mock
async def test_analyze_skin_end_to_end(client):
    respx.post(f"{BASE}/s2s/v2.0/file").mock(return_value=file_api_ok())
    respx.put(S3).mock(return_value=httpx.Response(200))
    create = respx.post(f"{BASE}/s2s/v2.0/task/skin-analysis").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"task_id": "T"}}))
    respx.get(f"{BASE}/s2s/v2.0/task/skin-analysis/T").mock(return_value=httpx.Response(200, json=SKIN_OK))
    rep = await analyze_skin(client, jpeg(), "image/jpeg")
    sent = create.calls[0].request.content
    assert b'"src_file_id":"FILE_1"' in sent.replace(b" ", b"") and b'"format":"json"' in sent.replace(b" ", b"")
    assert rep.score("moisture") == 52


def test_vto_payload_requires_exactly_one_of_each_source():
    with pytest.raises(ValueError):
        build_payload(src_file_id="a", src_file_url="b", ref_file_id="c")
    with pytest.raises(ValueError):
        build_payload(src_file_id="a")
    p = build_payload(src_file_id="a", ref_file_url="https://x/y.png", category=GarmentCategory.full_body)
    assert p["garment_category"] == "full_body" and p["ref_file_url"] and "ref_file_id" not in p


@respx.mock
async def test_try_on_end_to_end_with_garment_url(client):
    respx.post(f"{BASE}/s2s/v2.0/file").mock(return_value=file_api_ok("PERSON"))
    respx.put(S3).mock(return_value=httpx.Response(200))
    create = respx.post(f"{BASE}/s2s/v2.0/task/cloth-v4").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"task_id": "T"}}))
    respx.get(f"{BASE}/s2s/v2.0/task/cloth-v4/T").mock(return_value=httpx.Response(
        200, json={"status": 200, "data": {"task_status": "success", "error": None, "results": {"url": "https://out/r.png"}}}))
    res = await try_on_garment(
        client, person_image=jpeg(), person_content_type="image/jpeg",
        garment_url="https://shop/dress.png", category=GarmentCategory.full_body)
    assert res.image_url == "https://out/r.png" and "guarantee" in res.disclaimer
    body = create.calls[0].request.content.decode().replace(" ", "")
    assert '"src_file_id":"PERSON"' in body and '"ref_file_url":"https://shop/dress.png"' in body
