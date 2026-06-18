from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from git import Repo
from git.exc import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError

from .exceptions import PublishConflictError, PublishError, UnsafeRepositoryStateError, UpdateError
from .models import Finding, PublicationResult
from .result_repository import persist_findings


DEFAULT_PUBLISH_MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class RevisionStatus:
    current_revision: str | None
    target_revision: str | None
    resolved_revision: str | None
    is_behind: bool
    did_update: bool = False


def default_revision_status() -> RevisionStatus:
    return RevisionStatus(
        current_revision=None,
        target_revision=None,
        resolved_revision=None,
        is_behind=False,
        did_update=False,
    )


def sync_with_remote(repo_root: Path, *, remote_name: str, branch: str) -> RevisionStatus:
    repo = _open_repo(repo_root)
    try:
        current_revision = _head_revision(repo)
        target_revision = _fetch_target_revision(repo, remote_name, branch)
        _ensure_clean_worktree(repo)
        if current_revision == target_revision:
            return RevisionStatus(
                current_revision=current_revision,
                target_revision=target_revision,
                resolved_revision=current_revision,
                is_behind=False,
                did_update=False,
            )

        _pull_remote_branch(repo, remote_name, branch)
        resolved_revision = _head_revision(repo)
        if resolved_revision != target_revision:
            raise UpdateError(
                f"Post-update revision '{resolved_revision}' does not match target revision '{target_revision}'"
            )

        return RevisionStatus(
            current_revision=current_revision,
            target_revision=target_revision,
            resolved_revision=resolved_revision,
            is_behind=True,
            did_update=True,
        )
    finally:
        if hasattr(repo, "close"):
            repo.close()


def publish_findings_to_remote(
    repo_root: Path,
    *,
    remote_name: str,
    branch: str,
    result_path: Path,
    pi_id: str,
    revision: str | None,
    findings: list[Finding],
    max_push_attempts: int = DEFAULT_PUBLISH_MAX_ATTEMPTS,
    on_conflict: Callable[..., None] | None = None,
) -> PublicationResult:
    if max_push_attempts <= 0:
        raise PublishError("max_push_attempts must be greater than zero")

    repo_root = repo_root.resolve(strict=False)
    result_path = result_path.resolve(strict=False)
    result_relpath = _result_path_within_repo(repo_root, result_path)
    repo = _open_repo(repo_root)
    try:
        for attempt in range(1, max_push_attempts + 1):
            target_revision: str | None = None
            try:
                _ensure_publish_worktree(repo, allowed_paths={result_relpath})
                target_revision = _fetch_target_revision(repo, remote_name, branch)
                _reset_local_branch_to_target(repo, branch, target_revision)
                persistence_result = persist_findings(
                    result_path,
                    pi_id=pi_id,
                    revision=revision,
                    findings=findings,
                )
                committed = _commit_result_artifact(
                    repo,
                    result_relpath,
                    pi_id=pi_id,
                    branch=branch,
                    revision=revision,
                )
                published_revision = _push_remote_branch(repo, remote_name, branch)
                return PublicationResult(
                    artifact=persistence_result.artifact,
                    attempt_count=attempt,
                    conflict_retries=attempt - 1,
                    committed=committed,
                    published_revision=published_revision,
                )
            except PublishConflictError as exc:
                if attempt < max_push_attempts:
                    if on_conflict is not None:
                        on_conflict(attempt=attempt, max_attempts=max_push_attempts, error=str(exc))
                    continue
                _restore_publish_checkout(repo, branch=branch, target_revision=target_revision, result_relpath=result_relpath)
                raise PublishError(f"Unable to publish shared findings after {max_push_attempts} attempts") from exc
            except UnsafeRepositoryStateError:
                raise
            except (PublishError, UpdateError):
                _restore_publish_checkout(repo, branch=branch, target_revision=target_revision, result_relpath=result_relpath)
                raise
        raise PublishError(f"Unable to publish shared findings after {max_push_attempts} attempts")
    finally:
        if hasattr(repo, "close"):
            repo.close()


def _open_repo(repo_root: Path) -> Repo:
    try:
        return Repo(repo_root)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise UpdateError(f"Repository at '{repo_root}' is unavailable for revision checks") from exc


def _fetch_target_revision(repo: Repo, remote_name: str, branch: str) -> str:
    remote = _get_remote(repo, remote_name)
    try:
        remote.fetch(branch)
        return repo.commit(f"{remote_name}/{branch}").hexsha
    except GitCommandError as exc:
        raise UpdateError(f"Failed to fetch revision from '{remote_name}/{branch}'") from exc
    except (ValueError, BadName) as exc:
        raise UpdateError(f"Target revision '{remote_name}/{branch}' is unavailable after fetch") from exc


def _result_path_within_repo(repo_root: Path, result_path: Path) -> Path:
    try:
        return result_path.relative_to(repo_root)
    except ValueError as exc:
        raise PublishError(f"Result artifact '{result_path}' is not located inside repository '{repo_root}'") from exc


def _get_remote(repo: Repo, remote_name: str):
    for remote in repo.remotes:
        if remote.name == remote_name:
            return remote
    raise UpdateError(f"Configured git remote '{remote_name}' does not exist")


def _head_revision(repo: Repo) -> str:
    try:
        return repo.head.commit.hexsha
    except (ValueError, BadName, GitCommandError) as exc:
        raise UpdateError("Unable to determine the current HEAD revision safely") from exc


def _ensure_clean_worktree(repo: Repo) -> None:
    if repo.is_dirty(untracked_files=True):
        raise UnsafeRepositoryStateError("Local repository has uncommitted or untracked changes")


def _pull_remote_branch(repo: Repo, remote_name: str, branch: str) -> None:
    remote = _get_remote(repo, remote_name)
    try:
        remote.pull(branch, ff_only=True)
    except GitCommandError as exc:
        raise UpdateError(f"Failed to fast-forward local checkout from '{remote_name}/{branch}'") from exc


def _reset_local_branch_to_target(repo: Repo, branch: str, target_revision: str) -> None:
    try:
        repo.git.checkout(branch)
        repo.git.reset("--hard", target_revision)
    except GitCommandError as exc:
        raise PublishError(f"Failed to reset local checkout to '{branch}' at '{target_revision}'") from exc


def _ensure_publish_worktree(repo: Repo, *, allowed_paths: set[Path]) -> None:
    dirty_paths = []
    for normalized in _iter_porcelain_paths(repo.git.status("--porcelain", "-z", "--untracked-files=all")):
        if normalized not in allowed_paths:
            dirty_paths.append(normalized.as_posix())
    if dirty_paths:
        dirty_display = ", ".join(sorted(dirty_paths))
        raise UnsafeRepositoryStateError(
            f"Local repository has changes outside the shared result artifact: {dirty_display}"
        )


def _iter_porcelain_paths(status_output: str) -> list[Path]:
    entries = status_output.split("\0")
    parsed_paths: list[Path] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue

        status = entry[:2]
        path_text = entry[3:]
        if "R" in status or "C" in status:
            if index >= len(entries):
                raise PublishError("Unable to parse git status for publish worktree safety checks")
            path_text = entries[index]
            index += 1
        parsed_paths.append(Path(path_text))
    return parsed_paths


def _path_has_changes(repo: Repo, result_relpath: Path) -> bool:
    return bool(repo.git.status("--porcelain", "--", result_relpath.as_posix()).strip())


def _restore_publish_checkout(repo: Repo, *, branch: str, target_revision: str | None, result_relpath: Path) -> None:
    try:
        repo.git.checkout(branch)
        repo.git.reset("--hard", target_revision or "HEAD")
        repo.git.clean("-fd", "--", result_relpath.as_posix())
    except GitCommandError as exc:
        raise PublishError("Failed to restore a clean checkout after publish failure") from exc


def _commit_result_artifact(repo: Repo, result_relpath: Path, *, pi_id: str, branch: str, revision: str | None) -> bool:
    if not _path_has_changes(repo, result_relpath):
        return False

    try:
        repo.index.add([result_relpath.as_posix()])
        repo.index.commit(
            f"wind_events_crawler publish findings from {pi_id} on {branch}"
            + (f" ({revision})" if revision else "")
        )
    except (GitCommandError, OSError, ValueError) as exc:
        raise PublishError(f"Failed to commit shared result artifact '{result_relpath.as_posix()}'") from exc
    return True


def _push_remote_branch(repo: Repo, remote_name: str, branch: str) -> str:
    remote = _get_remote(repo, remote_name)
    refspec = f"HEAD:refs/heads/{branch}"
    try:
        push_results = remote.push(refspec=refspec)
    except GitCommandError as exc:
        if _is_push_conflict(str(exc)):
            raise PublishConflictError("non-fast-forward push rejected") from exc
        raise PublishError(f"Failed to push shared result artifact to '{remote_name}/{branch}'") from exc

    if not push_results:
        raise PublishError(f"Git push to '{remote_name}/{branch}' returned no result")

    push_result = push_results[0]
    summary = str(getattr(push_result, "summary", "") or "")
    rejected_flags = 0
    for flag_name in ("ERROR", "REJECTED", "REMOTE_REJECTED", "REMOTE_FAILURE"):
        rejected_flags |= getattr(type(push_result), flag_name, 0)

    if getattr(push_result, "flags", 0) & rejected_flags:
        if _is_push_conflict(summary):
            raise PublishConflictError("non-fast-forward push rejected")
        raise PublishError(
            f"Failed to push shared result artifact to '{remote_name}/{branch}'"
            + (f" ({summary})" if summary else "")
        )
    return _head_revision(repo)


def _is_push_conflict(message: str) -> bool:
    normalized = message.lower()
    return any(
        indicator in normalized
        for indicator in ("non-fast-forward", "fetch first", "failed to push some refs", "[rejected]")
    )
