# Sobe Kokoro TTS + thina-server (le .env para portas e KOKORO_DIR).
# Uso: .\scripts\start-services.ps1

$lib = Join-Path $PSScriptRoot "lib\services.ps1"
if (-not (Test-Path $lib)) {
    Write-Error "Nao encontrado: $lib"
    exit 1
}
. $lib

try {
    Start-ThinaStack
    exit 0
} catch {
    Write-Host "`nERRO: $($_.Exception.Message)`n" -ForegroundColor Red
    exit 1
}
