# Reinicia a stack Docker.

$lib = Join-Path $PSScriptRoot "lib\docker-stack.ps1"
if (-not (Test-Path $lib)) {
    Write-Error "Nao encontrado: $lib"
    exit 1
}
. $lib

try {
    Restart-DockerStack
    exit 0
} catch {
    Write-Host "`nERRO: $($_.Exception.Message)`n" -ForegroundColor Red
    exit 1
}
