# Sobe HA + Kokoro + thina-server via Docker Compose.
# Uso: .\start-docker.ps1
#      .\start-docker.ps1 -Build

param([switch]$Build)

$lib = Join-Path $PSScriptRoot "scripts\lib\docker-stack.ps1"
if (-not (Test-Path $lib)) {
    Write-Error "Nao encontrado: $lib"
    exit 1
}
. $lib

$kokoroApp = Join-Path $PSScriptRoot "kokoro\src\app.py"
if (-not (Test-Path $kokoroApp)) {
    Write-Host "Kokoro nao encontrado. Execute primeiro: .\install.ps1`n" -ForegroundColor Yellow
    & "$PSScriptRoot\install.ps1" -DockerOnly
}

if (-not $Build -and (Test-DockerStackImagesMissing)) {
    Write-Host "Imagens Docker ainda nao existem — build automatico na primeira execucao." -ForegroundColor Yellow
    $Build = $true
}

try {
    Start-DockerStack -Build:$Build
    exit 0
} catch {
    Write-Host "`nERRO: $($_.Exception.Message)`n" -ForegroundColor Red
    exit 1
}
