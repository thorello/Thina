# Instalacao inicial do projeto Thina (submodulo Kokoro + .env + venvs).
# Uso: .\install.ps1
#      .\install.ps1 -DockerOnly
#      .\install.ps1 -NativeOnly

param(
    [switch]$DockerOnly,
    [switch]$NativeOnly
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$KokoroDir = Join-Path $Root "kokoro"
$KokoroUrl = "https://github.com/thorello/kokoro.git"

function Write-Step([string]$Msg) {
    Write-Host "`n>> $Msg" -ForegroundColor Cyan
}

function Ensure-Kokoro {
    if (Test-Path (Join-Path $KokoroDir "src\app.py")) {
        Write-Host "  Kokoro OK em kokoro/" -ForegroundColor Green
        return
    }

    Write-Step "Obtendo Kokoro TTS (submodulo ou clone)"
    Push-Location $Root
    try {
        if (Test-Path ".gitmodules") {
            git submodule update --init --recursive 2>&1 | ForEach-Object { Write-Host "  $_" }
        }
        if (Test-Path (Join-Path $KokoroDir "src\app.py")) {
            Write-Host "  Kokoro via submodulo" -ForegroundColor Green
            return
        }

        if (Test-Path $KokoroDir) {
            Remove-Item $KokoroDir -Recurse -Force
        }
        git clone --depth 1 $KokoroUrl $KokoroDir 2>&1 | ForEach-Object { Write-Host "  $_" }
        if (-not (Test-Path (Join-Path $KokoroDir "src\app.py"))) {
            throw "Clone do Kokoro falhou. Verifique acesso a $KokoroUrl"
        }
        Write-Host "  Kokoro clonado em kokoro/" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

function Ensure-EnvFile {
    $envFile = Join-Path $Root ".env"
    $example = Join-Path $Root ".env.example"
    if (Test-Path $envFile) {
        Write-Host "  .env ja existe" -ForegroundColor Green
        return
    }
    if (-not (Test-Path $example)) {
        throw ".env.example nao encontrado"
    }
    Copy-Item $example $envFile
    Write-Host "  .env criado a partir de .env.example — edite chaves LLM e HOME_ASSISTANT_TOKEN" -ForegroundColor Yellow
}

function Ensure-PrivateMaps {
    $private = Join-Path $Root "maps\private"
    $example = Join-Path $Root "maps\private.example"
    if (Test-Path $private) { return }
    if (-not (Test-Path $example)) { return }
    Copy-Item $example $private -Recurse -Force
    Write-Host "  maps\private criado a partir de maps\private.example" -ForegroundColor Green
}

function Ensure-DataDirs {
    @(
        "data\audio",
        "data\run",
        "data\homeassistant"
    ) | ForEach-Object {
        $dir = Join-Path $Root $_
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
    $tts = Join-Path $Root "data\tts_settings.json"
    if (-not (Test-Path $tts)) {
        "{}" | Set-Content -Path $tts -Encoding UTF8 -NoNewline
    }
}

function Install-NativeVenvs {
    Write-Step "Ambiente Python nativo (thina-server + kokoro)"
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Host "  AVISO: python nao encontrado no PATH — pule venv ou instale Python 3.10+" -ForegroundColor Yellow
        return
    }

    $thinaVenv = Join-Path $Root ".venv"
    if (-not (Test-Path $thinaVenv)) {
        & python -m venv $thinaVenv
        & (Join-Path $thinaVenv "Scripts\pip.exe") install -r (Join-Path $Root "requirements.txt")
        Write-Host "  .venv do thina-server criado" -ForegroundColor Green
    } else {
        Write-Host "  .venv do thina-server ja existe" -ForegroundColor Green
    }

    $kokoroVenv = Join-Path $KokoroDir ".venv"
    if (-not (Test-Path $kokoroVenv)) {
        & python -m venv $kokoroVenv
        & (Join-Path $kokoroVenv "Scripts\pip.exe") install -r (Join-Path $KokoroDir "requirements.txt")
        Write-Host "  .venv do Kokoro criado" -ForegroundColor Green
    } else {
        Write-Host "  .venv do Kokoro ja existe" -ForegroundColor Green
    }

    $uiDir = Join-Path $Root "ui"
    if ((Test-Path $uiDir) -and -not (Test-Path (Join-Path $uiDir "node_modules"))) {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
        if ($npm) {
            Write-Host "  npm install em ui/ ..."
            & npm install --prefix $uiDir --no-fund --no-audit
        }
    }
}

Write-Host "`n=== Instalacao Thina Server ===" -ForegroundColor Cyan
Write-Host "Raiz: $Root"

Ensure-Kokoro
Ensure-EnvFile
Ensure-PrivateMaps
Ensure-DataDirs

if (-not $DockerOnly) {
    Install-NativeVenvs
}

Write-Host "`n=== Instalacao concluida ===" -ForegroundColor Cyan
if (-not $NativeOnly) {
    Write-Host "  Docker:  .\start-docker.ps1"
}
if (-not $DockerOnly) {
    Write-Host "  Nativo:  .\start.ps1"
}
Write-Host "  Status:  .\scripts\status-services.ps1`n"
