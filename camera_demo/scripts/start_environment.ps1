$ErrorActionPreference = 'Stop'
$Compose = Join-Path (Split-Path -Parent $PSScriptRoot) 'compose.camera.yaml'
docker compose -f $Compose up -d --pull never --no-build
if ($LASTEXITCODE -ne 0) { throw "Camera container startup failed: $LASTEXITCODE" }
docker compose -f $Compose ps
Write-Host 'Camera demo VNC: http://localhost:6083'
