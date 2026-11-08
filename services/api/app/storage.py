"""Object storage for call transcripts/receipts: S3-compatible (SeaweedFS/R2) primary, local disk fallback."""

import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger("callpay.storage")


class ObjectStore:
    def __init__(self, s3_url: str, bucket: str, local_dir: str, http: httpx.AsyncClient):
        self.s3_url, self.bucket, self.local, self.http = s3_url.rstrip("/"), bucket, Path(local_dir), http
        self.backend = "local"
        self._bucket_ready = False

    async def start(self) -> None:
        if not self.s3_url:
            return
        try:
            r = await self.http.put(f"{self.s3_url}/{self.bucket}", timeout=5)
            if r.status_code in (200, 409) or "BucketAlreadyOwnedByYou" in r.text or "BucketAlreadyExists" in r.text:
                self._bucket_ready, self.backend = True, "s3"
        except httpx.HTTPError as e:
            log.warning("object store unavailable (%s); using local disk", e)

    async def put_json(self, key: str, data: dict) -> str:
        body = json.dumps(data, default=str, indent=1).encode()
        if self._bucket_ready:
            try:
                r = await self.http.put(f"{self.s3_url}/{self.bucket}/{key}", content=body,
                                        headers={"Content-Type": "application/json"}, timeout=10)
                r.raise_for_status()
                return f"s3://{self.bucket}/{key}"
            except httpx.HTTPError as e:
                log.warning("S3 put failed (%s); writing to local disk", e)
        path = self.local / self.bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return f"file://{path}"
