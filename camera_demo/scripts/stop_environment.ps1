$ErrorActionPreference = 'Stop'
$Compose = Join-Path (Split-Path -Parent $PSScriptRoot) 'compose.camera.yaml'
docker compose -f $Compose stop
if ($LASTEXITCODE -ne 0) { throw "Camera container stop failed: $LASTEXITCODE" }
docker compose -f $Compose ps
