# Para a stack Docker (HA + Kokoro + thina-server).

$lib = Join-Path $PSScriptRoot "lib\docker-stack.ps1"
if (-not (Test-Path $lib)) {
    Write-Error "Nao encontrado: $lib"
    exit 1
}
. $lib

try {
    Stop-DockerStack
    exit 0
} catch {
    Write-Host "`nERRO: $($_.Exception.Message)`n" -ForegroundColor Red
    exit 1
}
