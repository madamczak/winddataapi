"""
storage.py — pluggable storage adapter.

Current implementation: LocalStorage (writes JSON files to disk).
Future: S3Storage / R2Storage using boto3 with an S3-compatible endpoint.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class StorageAdapter(ABC):
    """Abstract base — all adapters must implement write() and exists()."""

    @abstractmethod
    def write(self, key: str, data: str) -> None:
        """
        Persist *data* (a JSON string) under *key*.

        key  — relative path / object key, e.g. "kelmarsh/turbine_2/2018-05-30_20_raw.json"
        data — UTF-8 JSON string
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if the file/object for *key* already exists."""


class LocalStorage(StorageAdapter):
    """Write files to a local output directory."""

    def __init__(self, output_dir: str = "output") -> None:
        self.output_dir = Path(output_dir)

    def write(self, key: str, data: str) -> None:
        path = self.output_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")

    def exists(self, key: str) -> bool:
        return (self.output_dir / key).exists()


class S3Storage(StorageAdapter):
    """Write objects to AWS S3 (or any S3-compatible store such as Cloudflare R2)."""

    def __init__(self, bucket: str, prefix: str = "", endpoint_url: str | None = None) -> None:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise ImportError("boto3 is required for S3/R2 storage. Run: pip install boto3") from exc

        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def write(self, key: str, data: str) -> None:
        object_key = self.prefix + key
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=data.encode("utf-8"),
            ContentType="application/json",
        )

    def exists(self, key: str) -> bool:
        import botocore.exceptions  # type: ignore
        try:
            self.client.head_object(Bucket=self.bucket, Key=self.prefix + key)
            return True
        except botocore.exceptions.ClientError:
            return False


def build_storage(args) -> StorageAdapter:
    """Factory — build the right adapter from parsed CLI args."""
    if args.storage == "local":
        return LocalStorage(output_dir=args.output_dir)
    elif args.storage in ("s3", "r2"):
        endpoint = getattr(args, "endpoint", None)
        return S3Storage(
            bucket=args.bucket,
            prefix=getattr(args, "prefix", ""),
            endpoint_url=endpoint,
        )
    else:
        raise ValueError(f"Unknown storage backend: {args.storage!r}")

