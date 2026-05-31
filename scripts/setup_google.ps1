# Configura integracao Google (Gmail, Drive, Calendar) para a Thina.
# Abre o Google Cloud Console e, quando houver credenciais, autoriza a conta.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host ""
Write-Host "=== Thina — configuracao Google ===" -ForegroundColor Cyan
Write-Host ""

$dataDir = Join-Path $Root "data"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
}

$credsFile = Join-Path $dataDir "google_credentials.json"
$envFile = Join-Path $Root ".env"

Write-Host "Passo 1: abrindo Google Cloud Console..." -ForegroundColor Yellow
Write-Host "  - Ative Gmail API, Drive API e Calendar API"
Write-Host "  - Crie credencial OAuth tipo Desktop app"
Write-Host "  - Baixe o JSON OU copie Client ID + Client Secret para o .env"
Write-Host ""

Start-Process "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
Start-Sleep -Seconds 1
Start-Process "https://console.cloud.google.com/apis/library/drive.googleapis.com"
Start-Sleep -Seconds 1
Start-Process "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com"
Start-Sleep -Seconds 1
Start-Process "https://console.cloud.google.com/apis/credentials/consent"
Start-Sleep -Seconds 1
Start-Process "https://console.cloud.google.com/apis/credentials"

Write-Host "Passo 2: credenciais" -ForegroundColor Yellow
Write-Host "Opcao A — JSON: salve o arquivo baixado em:"
Write-Host "  $credsFile"
Write-Host ""
Write-Host "Opcao B — .env: adicione GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET"
Write-Host ""

if (-not (Test-Path $credsFile)) {
    $jsonPath = Read-Host "Caminho do JSON baixado (Enter para pular)"
    if ($jsonPath -and (Test-Path $jsonPath)) {
        Copy-Item $jsonPath $credsFile -Force
        Write-Host "JSON copiado para data/google_credentials.json" -ForegroundColor Green
    }
}

if (-not (Test-Path $credsFile)) {
    $clientId = Read-Host "Client ID (Enter se ja estiver no .env)"
    $clientSecret = Read-Host "Client Secret (Enter se ja estiver no .env)"
    if ($clientId -and $clientSecret -and (Test-Path $envFile)) {
        $lines = Get-Content $envFile -Raw
        if ($lines -notmatch "GOOGLE_CLIENT_ID=") {
            Add-Content $envFile "`nGOOGLE_CLIENT_ID=$clientId"
        }
        if ($lines -notmatch "GOOGLE_CLIENT_SECRET=") {
            Add-Content $envFile "GOOGLE_CLIENT_SECRET=$clientSecret"
        }
        Write-Host "Client ID/Secret gravados no .env" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Passo 3: autorizando conta Google (navegador)..." -ForegroundColor Yellow
python scripts/google_auth.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Autorizacao pendente. Rode de novo: python scripts/google_auth.py" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Pronto! A Thina pode ler Gmail, Drive e Calendar." -ForegroundColor Green
Write-Host "Teste: Thina, tenho email novo no Gmail?" -ForegroundColor Green
