# Para Kokoro TTS + thina-server iniciados por start-services.ps1.
# Uso: .\scripts\stop-services.ps1

$lib = Join-Path $PSScriptRoot "lib\services.ps1"
if (-not (Test-Path $lib)) {
    Write-Error "Nao encontrado: $lib"
    exit 1
}
. $lib

try {
    Stop-ThinaStack
    exit 0
} catch {
    Write-Host "`nERRO: $($_.Exception.Message)`n" -ForegroundColor Red
    exit 1
}
