from __future__ import annotations


class WorkerError(Exception):
    """Base exception for worker-specific failures."""


class ConfigError(WorkerError):
    """Raised when runtime configuration is missing or invalid."""


class ArtifactContractError(WorkerError):
    """Raised when the result artifact shape is invalid."""


class LockError(WorkerError):
    """Base exception for lock lifecycle failures."""


class LockActiveError(LockError):
    """Raised when another run still holds the worker lock."""

    def __init__(self, message: str, metadata):
        super().__init__(message)
        self.metadata = metadata


class LockAcquisitionError(LockError):
    """Raised when lock acquisition cannot complete safely."""


class LockReleaseError(LockError):
    """Raised when the worker cannot release its lock safely."""


class UpdateError(WorkerError):
    """Raised when repository revision checks or updates cannot complete safely."""


class UnsafeRepositoryStateError(UpdateError):
    """Raised when the local repository state is unsafe for self-update."""


class ApiRequestError(WorkerError):
    """Raised when the worker cannot retrieve the required API data safely."""


class ScenarioEvaluationError(WorkerError):
    """Raised when scenario evaluation cannot complete safely."""


class PublishError(WorkerError):
    """Raised when shared finding publication cannot complete safely."""


class PublishConflictError(PublishError):
    """Raised when publication hits a non-fast-forward or equivalent push race."""
