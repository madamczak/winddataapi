from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import time

from .exceptions import LockAcquisitionError, LockActiveError, LockReleaseError


@dataclass(frozen=True)
class LockInfo:
    path: Path
    stale_after_seconds: int = 1800


@dataclass(frozen=True)
class LockMetadata:
    run_id: str
    pi_id: str
    pid: int
    acquired_at_epoch_s: int
    acquired_at_utc: str

    def to_dict(self) -> dict[str, int | str]:
        return {
            "run_id": self.run_id,
            "pi_id": self.pi_id,
            "pid": self.pid,
            "acquired_at_epoch_s": self.acquired_at_epoch_s,
            "acquired_at_utc": self.acquired_at_utc,
        }


@dataclass(frozen=True)
class LockHandle:
    info: LockInfo
    metadata: LockMetadata
    recovered_stale_lock: bool = False


def build_lock_path(result_path: Path) -> Path:
    return result_path.with_suffix(".lock")


def _utc_from_epoch(epoch_seconds: int) -> str:
    return f"{epoch_seconds}"


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock_metadata(lock_path: Path) -> LockMetadata:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LockAcquisitionError(f"Lock file '{lock_path}' contains invalid JSON") from exc

    required = ("run_id", "pi_id", "pid", "acquired_at_epoch_s", "acquired_at_utc")
    if not isinstance(payload, dict) or any(key not in payload for key in required):
        raise LockAcquisitionError(f"Lock file '{lock_path}' is missing required metadata")

    return LockMetadata(
        run_id=str(payload["run_id"]),
        pi_id=str(payload["pi_id"]),
        pid=int(payload["pid"]),
        acquired_at_epoch_s=int(payload["acquired_at_epoch_s"]),
        acquired_at_utc=str(payload["acquired_at_utc"]),
    )


def _metadata_matches(left: LockMetadata, right: LockMetadata) -> bool:
    return left.to_dict() == right.to_dict()


def _is_resume_of_same_run(existing_metadata: LockMetadata, *, run_id: str, pi_id: str, pid: int) -> bool:
    return (
        existing_metadata.run_id == run_id
        and existing_metadata.pi_id == pi_id
        and existing_metadata.pid == pid
    )


def acquire_lock(
    lock_info: LockInfo,
    *,
    run_id: str,
    pi_id: str,
    now_epoch_s: int | None = None,
    pid: int | None = None,
) -> LockHandle:
    current_epoch = int(now_epoch_s if now_epoch_s is not None else time())
    current_pid = pid if pid is not None else os.getpid()
    recovered_stale_lock = False

    lock_info.path.parent.mkdir(parents=True, exist_ok=True)

    metadata = LockMetadata(
        run_id=run_id,
        pi_id=pi_id,
        pid=current_pid,
        acquired_at_epoch_s=current_epoch,
        acquired_at_utc=_utc_from_epoch(current_epoch),
    )

    while True:
        try:
            file_descriptor = os.open(lock_info.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            existing_metadata = _read_lock_metadata(lock_info.path)
            if _is_resume_of_same_run(existing_metadata, run_id=run_id, pi_id=pi_id, pid=current_pid):
                return LockHandle(info=lock_info, metadata=existing_metadata, recovered_stale_lock=False)
            lock_age_s = current_epoch - existing_metadata.acquired_at_epoch_s
            if lock_age_s < 0:
                raise LockAcquisitionError(f"Lock at '{lock_info.path}' has a future timestamp")
            if _pid_is_running(existing_metadata.pid):
                raise LockActiveError(f"Lock at '{lock_info.path}' is still active", existing_metadata)
            if lock_age_s <= lock_info.stale_after_seconds:
                raise LockAcquisitionError(
                    f"Lock at '{lock_info.path}' belongs to a dead process but is not yet stale"
                )

            refreshed_metadata = _read_lock_metadata(lock_info.path)
            if not _metadata_matches(existing_metadata, refreshed_metadata):
                continue
            try:
                lock_info.path.unlink()
            except FileNotFoundError:
                continue
            recovered_stale_lock = True

    with os.fdopen(file_descriptor, "w", encoding="utf-8") as lock_file:
        json.dump(metadata.to_dict(), lock_file)

    return LockHandle(info=lock_info, metadata=metadata, recovered_stale_lock=recovered_stale_lock)


def release_lock(lock_handle: LockHandle) -> None:
    try:
        if not lock_handle.info.path.exists():
            return
        existing_metadata = _read_lock_metadata(lock_handle.info.path)
        if not _metadata_matches(existing_metadata, lock_handle.metadata):
            raise LockReleaseError(f"Lock '{lock_handle.info.path}' is no longer owned by this run")
        lock_handle.info.path.unlink()
    except OSError as exc:
        raise LockReleaseError(f"Failed to release lock '{lock_handle.info.path}'") from exc
