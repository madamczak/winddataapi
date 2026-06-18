param(
    [switch]$RunWorker
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

python -m uv sync --directory $projectRoot

if ($RunWorker) {
    python -m uv run --directory $projectRoot wind-events-crawler
}
