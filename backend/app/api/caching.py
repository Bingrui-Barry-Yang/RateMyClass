"""ETag caching for responses that change only when the catalog is imported.

The response carries an ETag (sha256 of the body). A client that sends the same value back in
If-None-Match gets 304 Not Modified with no body, so unchanged data is not downloaded again.
"""

import hashlib
import json
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder

# Public data for other sites (/api/v1): shared caches may reuse it for five minutes without asking.
PUBLIC_5_MIN = "public, max-age=300"
# The browser may keep the response but must ask (with the ETag) before every use, so new data
# shows up right after an import while unchanged data costs only a 304.
REVALIDATE = "no-cache"


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    # "W/" marks a weak validator; proxies may add it. Compare the value only.
    sent = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
    return "*" in sent or etag in sent


def cached_json(request: Request, content: Any, cache_control: str = REVALIDATE) -> Response:
    body = json.dumps(jsonable_encoder(content), ensure_ascii=False, separators=(",", ":")).encode()
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)
