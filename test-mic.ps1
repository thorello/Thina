# Teste de voz com microfone (usa o .venv do projeto).
# Uso: .\test-mic.ps1
#      .\test-mic.ps1 --list-devices

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\test_mic.py"

if (-not (Test-Path $py)) {
    Write-Host "ERRO: .venv nao encontrado. Crie e instale dependencias:" -ForegroundColor Red
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\pip install -r requirements.txt -r requirements-mic.txt"
    exit 1
}

& $py $script @args
exit $LASTEXITCODE
