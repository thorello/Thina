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
        $cmd = "cd '$wslRoot' && docker compose " + ($Args -join " ")
        $out = & wsl -d $Cfg.WslDistro bash -lc $cmd 2>&1 | ForEach-Object { "$_" }
    } else {
        Push-Location $Cfg.Root
        try {
            $out = & docker compose @Args 2>&1 | ForEach-Object { "$_" }
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

function Start-DockerStack {
    param([switch]$Build)
    $cfg = Get-DockerStackConfig
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
