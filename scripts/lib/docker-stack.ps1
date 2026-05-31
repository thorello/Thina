# Funcoes Docker Compose para a stack Thina (HA + Kokoro + thina-server).
# Uso: . "$PSScriptRoot\lib\docker-stack.ps1"

$ErrorActionPreference = "Stop"

function Get-DockerStackConfig {
    $root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $envPath = Join-Path $root ".env"
    $env = @{}
    if (Test-Path $envPath) {
        foreach ($line in Get-Content $envPath -Encoding UTF8) {
            $line = $line.Trim()
            if (-not $line -or $line.StartsWith("#")) { continue }
            $eq = $line.IndexOf("=")
            if ($eq -lt 1) { continue }
            $key = $line.Substring(0, $eq).Trim()
            $val = $line.Substring($eq + 1).Trim()
            if ($val.Length -ge 2 -and $val.StartsWith('"') -and $val.EndsWith('"')) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            $env[$key] = $val
        }
    }

    $wslDistro = $env["WSL_DISTRO"]
    if (-not $wslDistro) { $wslDistro = "Ubuntu" }

    $useWsl = $false
    if ($env["DOCKER_VIA_WSL"] -eq "true") { $useWsl = $true }
    elseif (-not (Get-Command docker -ErrorAction SilentlyContinue)) { $useWsl = $true }

    return [PSCustomObject]@{
        Root      = $root
        Compose   = Join-Path $root "docker-compose.yml"
        WslDistro = $wslDistro
        UseWsl    = $useWsl
    }
}

function Get-DockerComposeCmd {
    param(
        [object]$Cfg,
        [switch]$UseWsl
    )
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($UseWsl) {
        & wsl -d $Cfg.WslDistro bash -lc "docker compose version" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $ErrorActionPreference = $prevEap
            return "docker compose"
        }
        & wsl -d $Cfg.WslDistro bash -lc "docker-compose --version" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $ErrorActionPreference = $prevEap
            return "docker-compose"
        }
        $ErrorActionPreference = $prevEap
        return "docker-compose"
    }
    & docker compose version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ErrorActionPreference = $prevEap
        return @("docker", "compose")
    }
    & docker-compose --version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ErrorActionPreference = $prevEap
        return @("docker-compose")
    }
    $ErrorActionPreference = $prevEap
    return @("docker", "compose")
}

function Invoke-DockerCompose {
    param(
        [object]$Cfg,
        [string[]]$Args
    )
    if (-not (Test-Path $Cfg.Compose)) {
        throw "Compose nao encontrado: $($Cfg.Compose)"
    }

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    if ($Cfg.UseWsl) {
        $wslRoot = & wsl -d $Cfg.WslDistro wslpath -a $Cfg.Root 2>&1
        if ($LASTEXITCODE -ne 0) {
            $ErrorActionPreference = $prevEap
            throw "wslpath falhou: $wslRoot"
        }
        $wslRoot = ($wslRoot | Out-String).Trim()
        $composeCmd = Get-DockerComposeCmd -Cfg $Cfg -UseWsl
        $cmd = "cd '$wslRoot' && $composeCmd " + ($Args -join " ")
        $out = & wsl -d $Cfg.WslDistro bash -lc $cmd 2>&1 | ForEach-Object { "$_" }
    } else {
        Push-Location $Cfg.Root
        try {
            $composeCmd = Get-DockerComposeCmd -Cfg $Cfg
            $out = & @($composeCmd + $Args) 2>&1 | ForEach-Object { "$_" }
        } finally {
            Pop-Location
        }
    }

    $exit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($exit -ne 0) {
        throw "docker compose falhou (exit $exit): $($Args -join ' ') | $out"
    }
    return $out
}

function Test-DockerStackImagesMissing {
    $cfg = Get-DockerStackConfig
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $images = docker images --format "{{.Repository}}" 2>$null
        if ($cfg.UseWsl) {
            $images = & wsl -d $cfg.WslDistro bash -lc "docker images --format '{{.Repository}}'" 2>$null
        }
        if (-not $images) { return $true }
        $hasThina = $false
        $hasKokoro = $false
        foreach ($line in ($images -split "`n")) {
            $repo = $line.Trim()
            if ($repo -eq 'thina-thina') { $hasThina = $true }
            if ($repo -eq 'thina-kokoro') { $hasKokoro = $true }
        }
        return -not ($hasThina -and $hasKokoro)
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Ensure-GoogleDockerFiles {
    param([string]$Root)
    $dataDir = Join-Path $Root "data"
    if (-not (Test-Path $dataDir)) {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    }
    foreach ($name in @("google_credentials.json", "google_token.json")) {
        $path = Join-Path $dataDir $name
        if (-not (Test-Path $path)) {
            "{}" | Set-Content -Path $path -Encoding UTF8 -NoNewline
        }
    }
}

function Start-DockerStack {
    param([switch]$Build)
    $cfg = Get-DockerStackConfig
    Ensure-GoogleDockerFiles -Root $cfg.Root
    Write-Host "`n=== Subindo stack Docker (HA + Kokoro + Thina) ===" -ForegroundColor Cyan
    Write-Host "Raiz: $($cfg.Root)"
    if ($cfg.UseWsl) {
        Write-Host "Docker via WSL ($($cfg.WslDistro))`n"
    }

    $args = @("up", "-d")
    if ($Build) { $args += "--build" }
    Invoke-DockerCompose -Cfg $cfg -Args $args | ForEach-Object { Write-Host $_ }

    Write-Host "`n=== Stack Docker iniciada ===" -ForegroundColor Cyan
    Write-Host "  HA:     http://127.0.0.1:8123"
    Write-Host "  Kokoro: http://127.0.0.1:8000/voices"
    Write-Host "  Thina:  http://127.0.0.1:8080/health"
    Write-Host "  UI:     http://127.0.0.1:8080/ui/"
    Write-Host "  Docs:   http://127.0.0.1:8080/docs`n"
}

function Stop-DockerStack {
    $cfg = Get-DockerStackConfig
    Write-Host "`n=== Parando stack Docker ===" -ForegroundColor Cyan
    Invoke-DockerCompose -Cfg $cfg -Args @("down") | ForEach-Object { Write-Host $_ }
    Write-Host "=== Stack Docker parada ===`n" -ForegroundColor Cyan
}

function Show-DockerStackStatus {
    $cfg = Get-DockerStackConfig
    Write-Host "`n=== Estado Docker Compose ===" -ForegroundColor Cyan
    Invoke-DockerCompose -Cfg $cfg -Args @("ps") | ForEach-Object { Write-Host $_ }
    Write-Host ""
}

function Restart-DockerStack {
    Stop-DockerStack
    Start-DockerStack -Build
}
