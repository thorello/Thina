# Estado de Kokoro + thina-server.
# Uso: .\scripts\status-services.ps1

$lib = Join-Path $PSScriptRoot "lib\services.ps1"
. $lib
Show-ThinaStackStatus
