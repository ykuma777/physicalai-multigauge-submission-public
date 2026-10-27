$ErrorActionPreference='Stop'
docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') stop simulator
if($LASTEXITCODE -ne 0){throw 'Failed to stop the isolated multigauge simulator.'}