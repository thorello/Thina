# Reinicia a stack completa (HA + Kokoro + Thina + UI).
# Para servicos em execucao e sobe de novo; se estiverem parados, apenas inicia.
# Uso: .\scripts\restart-services.ps1

$lib = Join-Path $PSScriptRoot "lib\services.ps1"
if (-not (Test-Path $lib)) {
    Write-Error "Nao encontrado: $lib"
    exit 1
}
. $lib

try {
    Restart-ThinaStack
    exit 0
} catch {
    Write-Host "`nERRO: $($_.Exception.Message)`n" -ForegroundColor Red
    exit 1
}
