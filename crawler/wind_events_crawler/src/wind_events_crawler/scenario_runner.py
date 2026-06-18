from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import ScenarioEvaluationError
from .models import ApiDataSlice, Finding, ScenarioEvaluationResult


_DEFAULT_SCENARIO = "data_presence"
_WIND_SPEED_FIELD = "Wind speed (m/s)"
_GENERATED_POWER_FIELD = "Power (kW)"


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    description: str


class ScenarioRunner:
    def __init__(self, scenarios: list[ScenarioDefinition] | None = None) -> None:
        self.scenarios = scenarios or [ScenarioDefinition(name=_DEFAULT_SCENARIO, description="Data presence detection")]

    def list_scenarios(self) -> list[str]:
        return [scenario.name for scenario in self.scenarios]

    def evaluate_active_scenario(
        self,
        payload: ApiDataSlice,
        *,
        scenario_name: str = _DEFAULT_SCENARIO,
    ) -> ScenarioEvaluationResult:
        if scenario_name != _DEFAULT_SCENARIO:
            raise ScenarioEvaluationError(f"Unsupported scenario '{scenario_name}'")

        total_rows = len(payload.rows)
        wind_speed_rows = {
            row_index
            for row_index, row in enumerate(payload.rows)
            if _row_contains_present_value(row, _WIND_SPEED_FIELD)
        }
        generated_power_rows = {
            row_index
            for row_index, row in enumerate(payload.rows)
            if _row_contains_present_value(row, _GENERATED_POWER_FIELD)
        }
        matching_rows = len(wind_speed_rows | generated_power_rows) if wind_speed_rows and generated_power_rows else 0
        matches = (
            [
                Finding(
                    scenario=scenario_name,
                    farm=payload.farm,
                    turbine=payload.turbine,
                    evaluated_window_start_utc=payload.evaluated_window_start_utc,
                    evaluated_window_end_utc=payload.evaluated_window_end_utc,
                )
            ]
            if matching_rows > 0
            else []
        )
        return ScenarioEvaluationResult(
            scenario=scenario_name,
            farm=payload.farm,
            turbine=payload.turbine,
            evaluated_window_start_utc=payload.evaluated_window_start_utc,
            evaluated_window_end_utc=payload.evaluated_window_end_utc,
            total_rows=total_rows,
            matching_rows=matching_rows,
            matches=matches,
        )


def _value_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _row_contains_present_value(row: object, field_name: str) -> bool:
    if not isinstance(row, dict):
        return False
    value = row.get(field_name)
    return _value_present(value)
