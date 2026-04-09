"""Async-friendly S3/MinIO client wrapper."""
import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import BinaryIO, Optional

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


class S3Client:
    def __init__(self):
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    def _run(self, fn, *args, **kwargs):
        """Run a synchronous S3 call in the thread pool."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(_executor, partial(fn, *args, **kwargs))

    async def upload(
        self,
        bucket: str,
        key: str,
        data: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> None:
        await self._run(
            self._client.upload_fileobj,
            data,
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    async def download(self, bucket: str, key: str) -> bytes:
        buf = io.BytesIO()
        await self._run(self._client.download_fileobj, bucket, key, buf)
        return buf.getvalue()

    async def get_presigned_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        url = await self._run(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    async def delete(self, bucket: str, key: str) -> None:
        await self._run(self._client.delete_object, Bucket=bucket, Key=key)

    async def exists(self, bucket: str, key: str) -> bool:
        try:
            await self._run(self._client.head_object, Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False
