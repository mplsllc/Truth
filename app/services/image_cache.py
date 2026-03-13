"""Cache article images to Cloudflare R2 via the Cloudflare API."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger(__name__)

# Content types we'll cache
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}


def _image_key(url: str) -> str:
    """Generate a deterministic key for an image URL."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    parsed = urlparse(url)
    ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "gif", "avif"):
        ext = "jpg"
    return f"images/{url_hash}.{ext}"


async def upload_to_r2(
    image_url: str,
    cf_account_id: str,
    r2_bucket: str,
    r2_api_token: str,
    r2_public_url: str,
) -> str | None:
    """Download an image and upload it to R2.

    Returns the public R2 URL, or None on failure.
    """
    key = _image_key(image_url)
    public_url = f"{r2_public_url.rstrip('/')}/{key}"

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # Check if already cached
            head_resp = await client.head(public_url)
            if head_resp.status_code == 200:
                return public_url

            # Download the image
            resp = await client.get(image_url)
            if resp.status_code != 200:
                return None

            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            if content_type not in ALLOWED_TYPES:
                return None

            # Skip very large images (> 5MB)
            if len(resp.content) > 5 * 1024 * 1024:
                return None

            # Upload to R2 via Cloudflare API
            upload_url = (
                f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}"
                f"/r2/buckets/{r2_bucket}/objects/{key}"
            )
            upload_resp = await client.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {r2_api_token}",
                    "Content-Type": content_type,
                },
                content=resp.content,
            )

            if upload_resp.status_code in (200, 201):
                await log.ainfo("image_cached", key=key, size=len(resp.content))
                return public_url
            else:
                await log.awarn(
                    "r2_upload_failed",
                    status=upload_resp.status_code,
                    body=upload_resp.text[:200],
                )
                return None

    except Exception as e:
        await log.awarn("image_cache_error", url=image_url, error=str(e))
        return None


async def cache_article_image(
    image_url: str | None,
    cf_account_id: str | None,
    r2_bucket: str | None,
    r2_api_token: str | None,
    r2_public_url: str | None,
) -> str | None:
    """Cache an article's image to R2 if configured. Returns the cached URL or original."""
    if not image_url:
        return None
    if not all([cf_account_id, r2_bucket, r2_api_token, r2_public_url]):
        return image_url  # R2 not configured, return original

    cached = await upload_to_r2(
        image_url, cf_account_id, r2_bucket, r2_api_token, r2_public_url
    )
    return cached or image_url  # Fall back to original on failure
