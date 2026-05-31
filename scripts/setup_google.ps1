# Conecta Gmail, Drive e Agenda — fluxo guiado para quem nao e tecnico.
# Uso: .\scripts\setup_google.ps1
#      Duplo clique em configurar-google.bat na raiz do projeto.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Title([string]$Msg) {
    Write-Host ""
    Write-Host "=== $Msg ===" -ForegroundColor Cyan
    Write-Host ""
}

function Ensure-GoogleEnabled {
    param([string]$EnvPath)
    if (-not (Test-Path $EnvPath)) {
        Write-Host "Arquivo .env nao encontrado. Rode .\install.ps1 primeiro." -ForegroundColor Red
        exit 1
    }
    $content = Get-Content $EnvPath -Raw
    if ($content -match "(?m)^GOOGLE_ENABLED\s*=\s*true\s*$") {
        return
    }
    if ($content -match "(?m)^GOOGLE_ENABLED\s*=") {
        $content = $content -replace "(?m)^GOOGLE_ENABLED\s*=.*$", "GOOGLE_ENABLED=true"
        Set-Content -Path $EnvPath -Value $content.TrimEnd() -NoNewline
        Add-Content -Path $EnvPath -Value "`n"
    } else {
        Add-Content -Path $EnvPath "`nGOOGLE_ENABLED=true"
    }
    Write-Host "GOOGLE_ENABLED=true definido no .env" -ForegroundColor Green
}

function Test-ThinaRunning {
    param([int]$Port = 8080)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Ensure-GoogleDataFiles {
    $dataDir = Join-Path $Root "data"
    if (-not (Test-Path $dataDir)) {
        New-Item -ItemType Directory -Path $dataDir | Out-Null
    }
    $token = Join-Path $dataDir "google_token.json"
    if (-not (Test-Path $token)) {
        "{}" | Set-Content -Path $token -Encoding UTF8 -NoNewline
    }
}

Write-Title "Thina — conectar Google"

$envFile = Join-Path $Root ".env"
$credsFile = Join-Path $Root "data\google_credentials.json"
$port = 8080
if (Test-Path $envFile) {
    $match = Select-String -Path $envFile -Pattern "^\s*THINA_PORT\s*=\s*(\d+)" | Select-Object -First 1
    if ($match) { $port = [int]$match.Matches[0].Groups[1].Value }
}

Ensure-GoogleDataFiles
Ensure-GoogleEnabled -EnvPath $envFile

$hasCredsFile = (Test-Path $credsFile) -and ((Get-Item $credsFile).Length -gt 10)
$hasEnvCreds = $false
if (Test-Path $envFile) {
    $envText = Get-Content $envFile -Raw
    $hasEnvCreds = $envText -match "GOOGLE_CLIENT_ID\s*=\s*\S+" -and $envText -match "GOOGLE_CLIENT_SECRET\s*=\s*\S+"
}

if (-not $hasCredsFile -and -not $hasEnvCreds) {
    Write-Host "Credenciais OAuth ainda nao foram colocadas." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Quem INSTALA a Thina para outra pessoa precisa fazer isto UMA vez:" -ForegroundColor Yellow
    Write-Host "  1. Criar app OAuth no Google Cloud (tipo Desktop)"
    Write-Host "  2. Colocar GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no .env"
    Write-Host "     OU salvar o JSON em data\google_credentials.json"
    Write-Host ""
    Write-Host "Guia completo: docs\integracao\google.md (secao Instalador)"
    Write-Host ""
    $openDoc = Read-Host "Abrir guia do instalador no navegador? (S/n)"
    if ($openDoc -ne "n" -and $openDoc -ne "N") {
        Start-Process "https://github.com/thorello/Thina/blob/main/docs/integracao/google.md"
    }
    $jsonPath = Read-Host "Caminho do JSON baixado do Google (Enter para pular)"
    if ($jsonPath -and (Test-Path $jsonPath)) {
        Copy-Item $jsonPath $credsFile -Force
        Write-Host "JSON copiado." -ForegroundColor Green
        $hasCredsFile = $true
    }
    if (-not $hasCredsFile -and -not $hasEnvCreds) {
        Write-Host "Sem credenciais — nao e possivel conectar a conta ainda." -ForegroundColor Red
        exit 1
    }
}

$setupUrl = "http://127.0.0.1:$port/v1/google/setup"

if (-not (Test-ThinaRunning -Port $port)) {
    Write-Host "A Thina nao esta rodando na porta $port." -ForegroundColor Yellow
    Write-Host "Subindo a stack Docker..."
    $startScript = Join-Path $Root "start-docker.ps1"
    if (Test-Path $startScript) {
        & $startScript
        Start-Sleep -Seconds 8
    } else {
        Write-Host "Rode .\start-docker.ps1 e execute este script de novo." -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-ThinaRunning -Port $port)) {
    Write-Host "Thina ainda offline. Verifique: docker compose ps" -ForegroundColor Red
    exit 1
}

Write-Host "Abrindo pagina para conectar sua conta Google..." -ForegroundColor Green
Write-Host "  $setupUrl"
Write-Host ""
Write-Host "Na pagina, clique em 'Conectar conta Google' e autorize no navegador."
Write-Host ""

Start-Process $setupUrl

Write-Host "Pronto! Depois de autorizar, teste por voz:" -ForegroundColor Green
Write-Host '  "Thina, tenho email novo no Gmail?"' -ForegroundColor Green
