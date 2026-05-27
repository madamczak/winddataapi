# Pytest Test Results Grafana Dashboard

This dashboard visualizes pytest test results (passed, failed, skipped) using Grafana Loki for log aggregation.

## Dashboard Features

The `pytest_dashboard.json` file contains a pre-configured Grafana dashboard with the following panels:

### Summary Statistics
- **Total Tests** - Number of test sessions
- **Passed Tests** - Count of passed tests (green)
- **Failed Tests** - Count of failed tests (red)
- **Skipped Tests** - Count of skipped tests (orange)
- **Pass Rate** - Percentage of passed tests with color-coded thresholds

### Visualizations
- **Test Results Summary** - Horizontal bar gauge showing passed/failed/skipped counts
- **Test Results Distribution** - Pie chart showing the distribution of test outcomes
- **Test Results Over Time** - Table view of all test results with timestamps
- **Test Duration Trend** - Time series showing test counts over time
- **Session Status** - Count of passed vs failed test sessions

## Prerequisites

1. **Grafana Loki** - Log aggregation system
2. **Loki Data Source** - Configured in Grafana pointing to your Loki instance
3. **Test Logging** - Tests must log to Loki with the following format:

## Log Format

The dashboard expects logs in this format (already configured in `conftest.py`):

```
TEST PASSED (Xs) [session_id]: test_name
TEST FAILED (Xs) [session_id]: test_name: error_message
TEST SKIPPED (Xs) [session_id]: test_name: skip_reason
SESSION PASSED (Xs): session_id=xxx, passed=X, failed=X, skipped=X, pass_rate=X.XX%
SESSION FAILED (Xs): session_id=xxx, passed=X, failed=X, skipped=X, pass_rate=X.XX%
```

## Loki Labels

The dashboard queries use these labels:
- `app="wind_data_tests"` - Application identifier
- `env="test"` - Environment (configurable)
- `level="info|error|warning"` - Log level

## Importing the Dashboard

1. Open Grafana
2. Go to **Dashboards** → **Import**
3. Upload the `pytest_dashboard.json` file
4. Select your Loki data source
5. Click **Import**

## Configuration

### Environment Variables

Set these in your test environment:

```bash
export GRAFANA_LOKI_INSTANCE_ID="your-instance-id"
export GRAFANA_TOKEN="your-grafana-token"
export GRAFANA_LOKI_URL="https://logs-prod-025.grafana.net/loki/api/v1/push"
export ENVIRONMENT="test"
```

### Template Variables

The dashboard includes template variables:
- `$environment` - Filter by environment (test, dev, staging, prod)
- `$time_range` - Time range for queries

## Queries Used

| Panel | Query |
|-------|-------|
| Passed Tests | `count_over_time({app="wind_data_tests", env="test", level="info"} |= "TEST PASSED" [$time_range])` |
| Failed Tests | `count_over_time({app="wind_data_tests", env="test", level="error"} |= "TEST FAILED" [$time_range])` |
| Skipped Tests | `count_over_time({app="wind_data_tests", env="test", level="warning"} |= "TEST SKIPPED" [$time_range])` |
| Pass Rate | `passed / (passed + failed + skipped) * 100` |

## Customization

To modify the dashboard:
1. Edit the JSON file directly
2. Or import and use Grafana's UI to make changes
3. Export the updated dashboard

## Troubleshooting

- **No data showing**: Verify Loki is receiving logs and the data source is configured correctly
- **Wrong counts**: Check the log format matches the expected patterns
- **Time range issues**: Adjust the `$time_range` variable or use Grafana's time picker