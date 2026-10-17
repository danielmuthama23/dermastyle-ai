"""Typed errors for the YouCam REST API, with shopper-friendly messages.

Error codes below come from the official YouCam docs (AI Skin Analysis and
AI Clothes file specs and error tables).
"""

from __future__ import annotations

USER_MESSAGES: dict[str, str] = {
    # Skin analysis preprocess
    "error_below_min_image_size": "That photo is too small. Use a larger, sharper photo.",
    "error_exceed_max_image_size": "That photo is too large. Try a smaller file.",
    "error_src_face_too_small": "Your face is too small in the photo. Move closer so it fills most of the frame.",
    "error_src_face_out_of_bound": "Part of your face is cut off. Center your face in the frame.",
    "error_lighting_dark": "The photo is too dark. Try again in bright, even light.",
    # Clothes preprocess / engine
    "exceed_max_filesize": "That image is too large. Keep files under 10 MB.",
    "error_pose": "We couldn't detect your pose. Use a front-facing, standing, full-length photo.",
    "error_invalid_ref": "The garment image isn't usable. Use a clear, front-facing product photo.",
    "error_apply_region_mismatch": "The garment doesn't match the area of your photo it should replace.",
    "error_invalid_src": "Your photo needs to show more of your body (not only lower body or feet).",
    "error_multi_person": "More than one person was detected. Use a photo with only you in it.",
    "error_download_image": "We couldn't download one of the images.",
    "error_nsfw_content_detected": "The result was blocked by the content filter.",
    "error_editing_failed": "The preview was too similar to the original. Try a different garment or photo.",
    "invalid_parameter": "The request had an invalid option.",
    "unknown_internal_error": "The try-on service had an internal problem. Please try again.",
    # Account / transport
    "CreditInsufficiency": "The demo has run out of API credits.",
    "InvalidAccessToken": "The server's YouCam API key is invalid.",
    "InvalidParameters": "The request had an invalid option.",
}


class YouCamError(Exception):
    """Any failure talking to the YouCam API."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retryable = retryable

    @property
    def user_message(self) -> str:
        if self.code and self.code in USER_MESSAGES:
            return USER_MESSAGES[self.code]
        return "The image service couldn't complete that request. Please try again."


class YouCamTaskError(YouCamError):
    """The task ran but ended with task_status == 'error'."""


class YouCamTimeout(YouCamError):
    """Polling gave up before the task reached a terminal state."""

    def __init__(self, task_id: str, waited_s: float) -> None:
        super().__init__(
            f"task {task_id} not finished after {waited_s:.0f}s",
            code="poll_timeout",
            retryable=True,
        )
        self.task_id = task_id

    @property
    def user_message(self) -> str:
        return "That is taking longer than expected. Please try again in a moment."
