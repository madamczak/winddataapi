from __future__ import annotations

import os
import sys
from uuid import uuid4

from .api_client import ApiClientConfig, RequestContext, WindDataApiClient
from .config import REPO_ROOT, WorkerConfig
from .exceptions import (
    ApiRequestError,
    LockAcquisitionError,
    LockActiveError,
    LockReleaseError,
    PublishError,
    ScenarioEvaluationError,
    UpdateError,
)
from .locking import LockInfo, acquire_lock, build_lock_path, release_lock
from .models import ApiDataSlice, ResultArtifact, RunContext, RunResult
from .result_repository import persist_findings
from .scenario_runner import ScenarioRunner
from .telemetry import emit_event, get_logger
from .updater import DEFAULT_PUBLISH_MAX_ATTEMPTS, publish_findings_to_remote, sync_with_remote


_RESUME_AFTER_UPDATE_ENV = "WIND_EVENTS_RESUME_AFTER_UPDATE"
_RESUME_RUN_ID_ENV = "WIND_EVENTS_RESUME_RUN_ID"
_RESUME_REVISION_ENV = "WIND_EVENTS_RESUME_REVISION"
_DEFAULT_SCENARIO = "data_presence"


class _ReexecRequested(BaseException):
    """Internal sentinel used by tests to simulate a successful exec replacement."""


def _new_run_id() -> str:
    return uuid4().hex


def _consume_resume_state() -> tuple[bool, str | None, str | None]:
    resumed = os.environ.pop(_RESUME_AFTER_UPDATE_ENV, "") == "1"
    if not resumed:
        os.environ.pop(_RESUME_RUN_ID_ENV, None)
        os.environ.pop(_RESUME_REVISION_ENV, None)
        return False, None, None

    return True, os.environ.pop(_RESUME_RUN_ID_ENV, None), os.environ.pop(_RESUME_REVISION_ENV, None)


def _build_context(config: WorkerConfig, *, run_id: str, stage: str, revision: str | None = None) -> RunContext:
    return RunContext(
        run_id=run_id,
        pi_id=config.pi_id,
        scenario=_DEFAULT_SCENARIO,
        stage=stage,
        lock_path=str(build_lock_path(config.result_path)),
        result_path=str(config.result_path),
        revision=revision,
    )


def _event_fields(context: RunContext, *, outcome: str, **extra: object) -> dict[str, object]:
    return {
        "run_id": context.run_id,
        "pi_id": context.pi_id,
        "revision": context.revision,
        "scenario": context.scenario,
        "stage": context.stage,
        "outcome": outcome,
        **extra,
    }


def _exec_self_after_update(*, run_id: str, revision: str) -> None:
    env = os.environ.copy()
    env[_RESUME_AFTER_UPDATE_ENV] = "1"
    env[_RESUME_RUN_ID_ENV] = run_id
    env[_RESUME_REVISION_ENV] = revision
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)
    raise RuntimeError("Process exec returned unexpectedly after successful update")


def initialize_worker(config: WorkerConfig | None = None) -> RunResult:
    resolved_config = config or WorkerConfig.from_env()
    logger = get_logger(config=resolved_config)
    resumed_after_update, resumed_run_id, resumed_revision = _consume_resume_state()
    run_id = resumed_run_id or _new_run_id()
    current_context = _build_context(resolved_config, run_id=run_id, stage="startup")
    run_error: Exception | None = None
    if not resumed_after_update:
        emit_event(logger, "run_started", **_event_fields(current_context, outcome="started"))

    lock_handle = None
    revision = None
    reexec_requested = False
    recovered_stale_lock = False
    scenario_result = None
    try:
        current_context = _build_context(resolved_config, run_id=run_id, stage="lock_acquisition")
        lock_handle = acquire_lock(
            LockInfo(
                path=build_lock_path(resolved_config.result_path),
                stale_after_seconds=resolved_config.stale_lock_timeout_s,
            ),
            run_id=run_id,
            pi_id=resolved_config.pi_id,
        )
        recovered_stale_lock = bool(lock_handle.recovered_stale_lock)
        if resumed_after_update:
            revision = resumed_revision
        elif lock_handle.recovered_stale_lock:
            emit_event(
                logger,
                "stale_lock_recovered",
                **_event_fields(current_context, outcome="recovered", lock_path=current_context.lock_path),
            )
        if not resumed_after_update:
            emit_event(
                logger,
                "lock_acquired",
                **_event_fields(current_context, outcome="acquired", lock_path=current_context.lock_path),
            )
    except LockActiveError as exc:
        emit_event(
            logger,
            "run_skipped",
            **_event_fields(current_context, outcome="skipped", lock_path=current_context.lock_path, active_run_id=exc.metadata.run_id),
        )
        return RunResult(context=current_context, outcome="skipped", artifact=None)
    except LockAcquisitionError:
        emit_event(
            logger,
            "run_failed",
            **_event_fields(current_context, outcome="failed"),
        )
        raise

    try:
        if resumed_after_update:
            if not revision:
                raise UpdateError("Updated process resumed without a resolved revision")
            current_context = _build_context(resolved_config, run_id=run_id, stage="update", revision=revision)
        else:
            current_context = _build_context(resolved_config, run_id=run_id, stage="update")
            emit_event(
                logger,
                "revision_check_started",
                **_event_fields(current_context, outcome="running"),
            )
            revision_status = sync_with_remote(
                REPO_ROOT,
                remote_name=resolved_config.git_remote_name,
                branch=resolved_config.git_branch,
            )
            revision = revision_status.resolved_revision
            current_context = _build_context(resolved_config, run_id=run_id, stage="update", revision=revision)
            emit_event(
                logger,
                "update_applied" if revision_status.did_update else "update_skipped",
                **_event_fields(
                    current_context,
                    outcome="updated" if revision_status.did_update else "current",
                    current_revision=revision_status.current_revision,
                    target_revision=revision_status.target_revision,
                ),
            )
            if revision_status.did_update and revision is not None:
                try:
                    _exec_self_after_update(run_id=run_id, revision=revision)
                except _ReexecRequested:
                    reexec_requested = True
                    raise
        current_context = _build_context(resolved_config, run_id=run_id, stage="execution", revision=revision)
        emit_event(
            logger,
            "execution_started",
            **_event_fields(current_context, outcome="running", result_path=current_context.result_path),
        )
        current_context = _build_context(resolved_config, run_id=run_id, stage="api", revision=revision)
        api_client = WindDataApiClient(
            ApiClientConfig(
                api_base_url=resolved_config.api_base_url,
                request_delay_seconds=resolved_config.request_delay_seconds,
                max_retries=resolved_config.api_max_retries,
                backoff_base_seconds=resolved_config.api_backoff_base_seconds,
                backoff_jitter_seconds=resolved_config.api_backoff_jitter_seconds,
            )
        )
        payload = api_client.fetch_data_slice(
            farm=resolved_config.scenario_farm,
            turbine=resolved_config.scenario_turbine,
            evaluated_window_start_utc=resolved_config.scenario_window_start_utc,
            evaluated_window_end_utc=resolved_config.scenario_window_end_utc,
            logger=logger,
            context=RequestContext(
                run_id=current_context.run_id,
                pi_id=current_context.pi_id,
                scenario=current_context.scenario,
                stage=current_context.stage,
            ),
        )
        current_context = _build_context(resolved_config, run_id=run_id, stage="scenario", revision=revision)
        scenario_runner = ScenarioRunner()
        scenario_result = scenario_runner.evaluate_active_scenario(
            ApiDataSlice(
                farm=str(payload.get("farm", resolved_config.scenario_farm)),
                turbine=str(payload.get("turbine", resolved_config.scenario_turbine)),
                evaluated_window_start_utc=resolved_config.scenario_window_start_utc,
                evaluated_window_end_utc=resolved_config.scenario_window_end_utc,
                rows=list(payload.get("rows", [])),
                data_type=str(payload.get("data_type", "data")),
            ),
            scenario_name=current_context.scenario,
        )
        emit_event(
            logger,
            "scenario_evaluation_completed",
            **_event_fields(
                current_context,
                outcome="matched" if scenario_result.matches else "no_match",
                total_rows=scenario_result.total_rows,
                matching_rows=scenario_result.matching_rows,
                finding_candidates=len(scenario_result.matches),
                farm=scenario_result.farm,
                turbine=scenario_result.turbine,
            ),
        )
        current_context = _build_context(resolved_config, run_id=run_id, stage="persistence", revision=revision)
        persistence_result = persist_findings(
            resolved_config.result_path,
            pi_id=resolved_config.pi_id,
            revision=revision,
            findings=scenario_result.matches,
        )
        emit_event(
            logger,
            "finding_persistence_completed",
            **_event_fields(
                current_context,
                outcome="merged" if persistence_result.added_findings > 0 else "no_new_findings",
                incoming_findings=persistence_result.incoming_findings,
                preserved_findings=persistence_result.preserved_findings,
                added_findings=persistence_result.added_findings,
                total_findings=persistence_result.stored_findings,
                result_path=current_context.result_path,
            ),
        )
        current_context = _build_context(resolved_config, run_id=run_id, stage="publish", revision=revision)

        def _record_publish_conflict(*, attempt: int, max_attempts: int, error: str) -> None:
            emit_event(
                logger,
                "publish_conflict",
                **_event_fields(
                    current_context,
                    outcome="conflict",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=error,
                ),
            )
            emit_event(
                logger,
                "publish_retry_scheduled",
                **_event_fields(
                    current_context,
                    outcome="retrying",
                    attempt=attempt,
                    next_attempt=attempt + 1,
                    max_attempts=max_attempts,
                ),
            )

        publication_result = publish_findings_to_remote(
            REPO_ROOT,
            remote_name=resolved_config.git_remote_name,
            branch=resolved_config.git_branch,
            result_path=resolved_config.result_path,
            pi_id=resolved_config.pi_id,
            revision=revision,
            findings=scenario_result.matches,
            max_push_attempts=DEFAULT_PUBLISH_MAX_ATTEMPTS,
            on_conflict=_record_publish_conflict,
        )
        artifact = publication_result.artifact
        emit_event(
            logger,
            "publish_succeeded",
            **_event_fields(
                current_context,
                outcome="published",
                result_path=current_context.result_path,
                attempt_count=publication_result.attempt_count,
                conflict_retries=publication_result.conflict_retries,
                committed=publication_result.committed,
                total_findings=len(artifact.findings),
                published_revision=publication_result.published_revision,
            ),
        )
        current_context = _build_context(resolved_config, run_id=run_id, stage="completion", revision=revision)
        completed_lock_handle = lock_handle
        lock_handle = None
        release_lock(completed_lock_handle)
        current_context = _build_context(resolved_config, run_id=run_id, stage="completion", revision=revision)
        emit_event(
            logger,
            "run_completed",
            **_event_fields(
                current_context,
                outcome="completed",
                result_path=current_context.result_path,
                schema_version=artifact.schema_version,
            ),
        )
        return RunResult(
            context=current_context,
            outcome="completed",
            artifact=artifact,
            recovered_stale_lock=recovered_stale_lock,
            scenario_result=scenario_result,
        )
    except (ApiRequestError, ScenarioEvaluationError, UpdateError, PublishError) as exc:
        run_error = exc
        if isinstance(exc, PublishError) or (isinstance(exc, UpdateError) and current_context.stage == "publish"):
            emit_event(
                logger,
                "publish_failed",
                **_event_fields(
                    current_context,
                    outcome="failed",
                    error=str(exc),
                    max_attempts=DEFAULT_PUBLISH_MAX_ATTEMPTS,
                ),
            )
        emit_event(
            logger,
            "run_failed",
            **_event_fields(current_context, outcome="failed"),
        )
        raise
    except Exception as exc:
        run_error = exc
        emit_event(
            logger,
            "run_failed",
            **_event_fields(current_context, outcome="failed"),
        )
        raise
    finally:
        if lock_handle is not None and not reexec_requested:
            try:
                release_lock(lock_handle)
            except LockReleaseError as exc:
                cleanup_context = _build_context(
                    resolved_config,
                    run_id=run_id,
                    stage="completion",
                    revision=current_context.revision,
                )
                if run_error is not None:
                    run_error.add_note(f"Lock release failed during cleanup: {exc}")
                    emit_event(
                        logger,
                        "lock_release_failed",
                        **_event_fields(cleanup_context, outcome="failed", error=str(exc)),
                    )
                else:
                    emit_event(
                        logger,
                        "run_failed",
                        **_event_fields(cleanup_context, outcome="failed"),
                    )
                    raise
