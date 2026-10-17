import io

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.youcam import YouCamClient

BASE = "https://yce-api-01.makeupar.com"
S3 = "https://yce-us.s3-accelerate.amazonaws.com/upload/abc"


def make_settings(**kw) -> Settings:
    base = dict(
        youcam_api_key="test-key", youcam_poll_initial_s=0.0, youcam_poll_max_s=0.0,
        youcam_retry_base_s=0.0, youcam_poll_deadline_s=1.0, youcam_max_retries=2,
    )
    base.update(kw)
    return Settings(**base)


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client(settings):
    http = httpx.AsyncClient()
    c = YouCamClient(settings, http=http, sleep=no_sleep)
    yield c
    await http.aclose()


def jpeg(w=600, h=800, color=(180, 140, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


def png(w=600, h=800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 10, 10)).save(buf, format="PNG")
    return buf.getvalue()


def file_api_ok(file_id="FILE_1"):
    return httpx.Response(
        200,
        json={"status": 200, "data": {"files": [{
            "content_type": "image/jpg", "file_name": "x.jpg", "file_id": file_id,
            "requests": [{"method": "PUT", "url": S3, "headers": {"Content-Type": "image/jpg"}}],
        }]}},
    )
