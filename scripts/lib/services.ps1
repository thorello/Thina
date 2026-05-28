# Funcoes partilhadas para subir/parar a stack Thina (Home Assistant + Kokoro + thina-server).
# Docker: via WSL (wsl docker / wsl docker compose). Uso: . "$PSScriptRoot\lib\services.ps1"

$ErrorActionPreference = "Stop"

function Get-ThinaRoot {
    # scripts/lib -> raiz do repo
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-RunDir {
    param([string]$Root = (Get-ThinaRoot))
    $dir = Join-Path $Root "data\run"
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    return $dir
}

function Read-EnvFile {
    param([string]$Path)
    $vars = @{}
    if (-not (Test-Path $Path)) { return $vars }
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { continue }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim()
        if ($val.Length -ge 2 -and $val.StartsWith('"') -and $val.EndsWith('"')) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $vars[$key] = $val
    }
    return $vars
}

function Get-StackConfig {
    $root = Get-ThinaRoot
    $envPath = Join-Path $root ".env"
    $env = Read-EnvFile $envPath

    $kokoroDir = $env["KOKORO_DIR"]
    if (-not $kokoroDir) {
        $kokoroDir = Join-Path (Split-Path $root -Parent) "kokoro"
    } elseif (-not [System.IO.Path]::IsPathRooted($kokoroDir)) {
        $kokoroDir = Join-Path $root $kokoroDir
    }
    $resolved = Resolve-Path $kokoroDir -ErrorAction SilentlyContinue
    if ($resolved) {
        $kokoroDir = $resolved.Path
    } elseif (-not (Test-Path $kokoroDir)) {
        $kokoroDir = Join-Path (Split-Path $root -Parent) "kokoro"
    }

    $thinaPort = 8080
    if ($env["THINA_PORT"]) { [void][int]::TryParse($env["THINA_PORT"], [ref]$thinaPort) }

    $kokoroPort = 8000
    $kokoroUrl = $env["KOKORO_SERVER_URL"]
    if ($kokoroUrl -match ':(\d+)\s*$') { $kokoroPort = [int]$Matches[1] }

    $thinaVenv = Join-Path $root ".venv\Scripts\python.exe"
    $kokoroVenv = Join-Path $kokoroDir ".venv\Scripts\python.exe"

    $haPort = 8123
    $haUrl = $env["HOME_ASSISTANT_URL"]
    if ($haUrl -match ':(\d+)\s*$') { $haPort = [int]$Matches[1] }

    $haManaged = $true
    if ($env["HOME_ASSISTANT_MANAGED"] -eq "false") { $haManaged = $false }

    return [PSCustomObject]@{
        Root          = $root
        RunDir        = Get-RunDir $root
        KokoroDir     = $kokoroDir
        ThinaPort     = $thinaPort
        KokoroPort    = $kokoroPort
        HaPort        = $haPort
        HaManaged     = $haManaged
        HaComposeDir  = Join-Path $root "scripts\ha"
        HaContainer   = "thina-homeassistant"
        WslDistro     = $env["WSL_DISTRO"]
        ThinaPy       = if (Test-Path $thinaVenv) { $thinaVenv } else { "python" }
        KokoroPy      = if (Test-Path $kokoroVenv) { $kokoroVenv } else { "python" }
    }
}

function Get-WslExeArgs {
    param([object]$Cfg)
    $args = @()
    if ($Cfg.WslDistro) {
        $args += "-d", $Cfg.WslDistro
    }
    return $args
}

function ConvertTo-WslPath {
    param([string]$WindowsPath)
    $resolved = (Resolve-Path $WindowsPath -ErrorAction Stop).Path
    # Barras normais: PowerShell apaga '\' ao passar argumentos ao wsl.exe
    $winPath = $resolved.Replace("\", "/")
    $wslBase = Get-WslExeArgs (Get-StackConfig)
    $out = & wsl @wslBase wslpath -a $winPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "wslpath falhou para '$resolved': $out"
    }
    return ($out | Out-String).Trim()
}

function Invoke-WslCommand {
    param(
        [object]$Cfg,
        [string[]]$Command
    )
    $wslBase = Get-WslExeArgs $Cfg
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $out = & wsl @wslBase @Command 2>&1 | ForEach-Object { "$_" }
    $exit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($exit -ne 0) {
        throw "Comando WSL falhou (exit $exit): $($Command -join ' ') | $out"
    }
    return $out
}

function Invoke-WslDocker {
    param(
        [object]$Cfg,
        [string[]]$DockerArgs
    )
    $dockerCmd = @("docker") + @($DockerArgs)
    return Invoke-WslCommand -Cfg $Cfg -Command $dockerCmd
}

function Test-WslDocker {
    param([object]$Cfg)
    try {
        Invoke-WslDocker -Cfg $Cfg -DockerArgs @("version", "--format", "{{.Server.Version}}") | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-HomeAssistantContainerRunning {
    param([object]$Cfg)
    try {
        foreach ($name in @($Cfg.HaContainer, "homeassistant")) {
            $out = Invoke-WslDocker -Cfg $Cfg -DockerArgs @(
                "ps", "--filter", "name=^/${name}$", "--filter", "status=running", "-q"
            )
            if (($out | Out-String).Trim()) { return $true }
        }
        return $false
    } catch {
        return $false
    }
}

function Test-HomeAssistantHttp {
    param([object]$Cfg)
    return Wait-HttpOk "http://127.0.0.1:$($Cfg.HaPort)/" 5 1
}

function Start-HomeAssistant {
    param([object]$Cfg)
    if (-not $Cfg.HaManaged) {
        Write-Host "  [homeassistant] HOME_ASSISTANT_MANAGED=false - ignorado" -ForegroundColor DarkGray
        return
    }
    if (-not (Test-WslDocker $Cfg)) {
        throw "Docker nao encontrado no WSL. Instale no WSL ou defina WSL_DISTRO no .env."
    }

    $composeFile = Join-Path $Cfg.HaComposeDir "docker-compose.yml"
    if (-not (Test-Path $composeFile)) {
        throw "Compose nao encontrado: $composeFile"
    }

    $haConfig = Join-Path $Cfg.Root "data\homeassistant"
    if (-not (Test-Path $haConfig)) {
        New-Item -ItemType Directory -Path $haConfig -Force | Out-Null
    }

    $haUrl = "http://127.0.0.1:$($Cfg.HaPort)/"

    if (Test-HomeAssistantHttp $Cfg) {
        Write-Host "  [homeassistant] ja responde em $haUrl" -ForegroundColor Green
        return
    }

    if (Test-HomeAssistantContainerRunning $Cfg) {
        Write-Host "  [homeassistant] container em execucao, aguardando HTTP ..."
    } else {
        $wslHaDir = ConvertTo-WslPath $Cfg.HaComposeDir
        Write-Host "  [homeassistant] docker compose up (WSL) ..."
        try {
            Invoke-WslCommand -Cfg $Cfg -Command @(
                "bash", "-lc",
                "export HA_HOST_PORT=$($Cfg.HaPort); cd '$wslHaDir'; docker compose up -d"
            ) | Out-Null
            Write-Host "  [homeassistant] container iniciado" -ForegroundColor Green
        } catch {
            if (Test-HomeAssistantHttp $Cfg) {
                Write-Host "  [homeassistant] porta $($Cfg.HaPort) em uso por outro HA (OK)" -ForegroundColor Yellow
            } else {
                Invoke-WslDocker -Cfg $Cfg -DockerArgs @("rm", "-f", $Cfg.HaContainer) 2>$null | Out-Null
                throw
            }
        }
    }

    Write-Host "  Aguardando $haUrl (primeira subida pode demorar varios minutos) ..."
    if (-not (Wait-HttpOk $haUrl 300)) {
        Write-Host "  AVISO: HA ainda nao respondeu. Veja: wsl docker logs homeassistant" -ForegroundColor Yellow
    } else {
        Write-Host "  Home Assistant OK" -ForegroundColor Green
    }
}

function Stop-HomeAssistant {
    param([object]$Cfg)
    if (-not $Cfg.HaManaged) {
        Write-Host "  [homeassistant] HOME_ASSISTANT_MANAGED=false - ignorado" -ForegroundColor DarkGray
        return
    }
    if (-not (Test-WslDocker $Cfg)) {
        Write-Host "  [homeassistant] Docker/WSL indisponivel" -ForegroundColor DarkGray
        return
    }

    $stopped = $false
    try {
        $managed = Invoke-WslDocker -Cfg $Cfg -DockerArgs @(
            "ps", "-a", "--filter", "name=^/$($Cfg.HaContainer)$", "-q"
        )
        if (($managed | Out-String).Trim()) {
            $wslHaDir = ConvertTo-WslPath $Cfg.HaComposeDir
            Invoke-WslCommand -Cfg $Cfg -Command @(
                "bash", "-lc",
                "cd '$wslHaDir'; docker compose down"
            ) | Out-Null
            $stopped = $true
        }
    } catch {
        Invoke-WslDocker -Cfg $Cfg -DockerArgs @("rm", "-f", $Cfg.HaContainer) 2>$null | Out-Null
        $stopped = $true
    }

    if ($stopped) {
        Write-Host "  [homeassistant] container $($Cfg.HaContainer) parado" -ForegroundColor Green
    } else {
        Write-Host "  [homeassistant] $($Cfg.HaContainer) ausente (container 'homeassistant' externo nao e parado)" -ForegroundColor DarkGray
    }
}

function Get-PidFilePath {
    param([string]$Name, [string]$RunDir)
    return Join-Path $RunDir "$Name.pid"
}

function Get-ListenerPid {
    param([int]$Port)
    $lines = netstat -ano 2>$null | Select-String ":\s*$Port\s+.*LISTENING"
    foreach ($line in $lines) {
        if ($line -match '\s+(\d+)\s*$') {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Test-ProcessAlive {
    param([int]$ProcessId)
    if (-not $ProcessId) { return $false }
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSec = 90,
        [int]$IntervalSec = 2
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { return $true }
        } catch { }
        Start-Sleep -Seconds $IntervalSec
    }
    return $false
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string]$Python,
        [string[]]$Arguments,
        [string]$RunDir
    )
    $pidFile = Get-PidFilePath $Name $RunDir
    if (Test-Path $pidFile) {
        $oldPid = [int](Get-Content $pidFile -Raw)
        if (Test-ProcessAlive $oldPid) {
            Write-Host "  [$Name] ja em execucao (PID $oldPid)" -ForegroundColor Yellow
            return $oldPid
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    $outLog = Join-Path $RunDir "$Name.stdout.log"
    $errLog = Join-Path $RunDir "$Name.stderr.log"

    $proc = Start-Process `
        -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog

    $proc.Id | Set-Content -Path $pidFile -Encoding ASCII -NoNewline
    Write-Host "  [$Name] iniciado PID $($proc.Id) | logs: data\run\$Name.*.log" -ForegroundColor Green
    return $proc.Id
}

function Stop-ManagedProcess {
    param(
        [string]$Name,
        [int]$Port,
        [string]$RunDir
    )
    $pidFile = Get-PidFilePath $Name $RunDir
    $stopped = $false

    if (Test-Path $pidFile) {
        $procId = [int](Get-Content $pidFile -Raw)
        if (Test-ProcessAlive $procId) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Host "  [$Name] parado (PID $procId)" -ForegroundColor Green
            $stopped = $true
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    $portPid = Get-ListenerPid $Port
    if ($portPid -and (Test-ProcessAlive $portPid)) {
        $proc = Get-Process -Id $portPid -ErrorAction SilentlyContinue
        $isPython = $proc -and ($proc.ProcessName -match 'python')
        if ($isPython -and -not $stopped) {
            Stop-Process -Id $portPid -Force -ErrorAction SilentlyContinue
            Write-Host "  [$Name] processo na porta $Port parado (PID $portPid)" -ForegroundColor Green
            $stopped = $true
        } elseif ($isPython -and $stopped) {
            # Pid file matou outro processo; ainda ha listener na porta
            Stop-Process -Id $portPid -Force -ErrorAction SilentlyContinue
            Write-Host "  [$Name] listener extra na porta $Port parado (PID $portPid)" -ForegroundColor Yellow
        }
    }

    if (-not $stopped) {
        Write-Host "  [$Name] nao estava em execucao" -ForegroundColor DarkGray
    }
}

function Start-ThinaStack {
    $cfg = Get-StackConfig
    Write-Host "`n=== Subindo servicos Thina ===" -ForegroundColor Cyan
    Write-Host "Raiz: $($cfg.Root)"
    Write-Host "Kokoro: $($cfg.KokoroDir) :$($cfg.KokoroPort)"
    Write-Host "Thina:  :$($cfg.ThinaPort)"
    if ($cfg.HaManaged) {
        Write-Host "HA:     http://127.0.0.1:$($cfg.HaPort) (Docker no WSL)`n"
    } else {
        Write-Host "HA:     externo (HOME_ASSISTANT_MANAGED=false)`n"
    }

    if (-not (Test-Path $cfg.KokoroDir)) {
        throw "Pasta Kokoro nao encontrada: $($cfg.KokoroDir). Defina KOKORO_DIR no .env"
    }
    if (-not (Test-Path (Join-Path $cfg.KokoroDir "src\app.py"))) {
        throw "src\app.py nao encontrado em $($cfg.KokoroDir)"
    }

    # 1) Home Assistant (Docker/WSL)
    if ($cfg.HaManaged) {
        Write-Host "[1/3] Home Assistant"
        Start-HomeAssistant $cfg
    }

    # 2) Kokoro (TTS)
    Write-Host $(if ($cfg.HaManaged) { "`n[2/3] Kokoro TTS" } else { "[1/2] Kokoro TTS" })
    Start-ManagedProcess `
        -Name "kokoro" `
        -WorkingDirectory $cfg.KokoroDir `
        -Python $cfg.KokoroPy `
        -Arguments @("src\app.py") `
        -RunDir $cfg.RunDir | Out-Null

    $kokoroHealth = "http://127.0.0.1:$($cfg.KokoroPort)/voices"
    Write-Host "  Aguardando $kokoroHealth ..."
    if (-not (Wait-HttpOk $kokoroHealth 120)) {
        Write-Host "  AVISO: Kokoro nao respondeu a tempo. Veja data\run\kokoro.stderr.log" -ForegroundColor Yellow
    } else {
        Write-Host "  Kokoro OK" -ForegroundColor Green
    }

    # 3) Thina
    Write-Host $(if ($cfg.HaManaged) { "`n[3/3] thina-server" } else { "`n[2/2] thina-server" })
    Start-ManagedProcess `
        -Name "thina" `
        -WorkingDirectory $cfg.Root `
        -Python $cfg.ThinaPy `
        -Arguments @("main.py") `
        -RunDir $cfg.RunDir | Out-Null

    $thinaHealth = "http://127.0.0.1:$($cfg.ThinaPort)/health"
    Write-Host "  Aguardando $thinaHealth ..."
    if (-not (Wait-HttpOk $thinaHealth 60)) {
        Write-Host "  AVISO: Thina nao respondeu a tempo. Veja data\run\thina.stderr.log" -ForegroundColor Yellow
    } else {
        Write-Host "  Thina OK" -ForegroundColor Green
    }

    Write-Host "`n=== Stack pronta ===" -ForegroundColor Cyan
    if ($cfg.HaManaged) {
        Write-Host "  HA:      http://127.0.0.1:$($cfg.HaPort) (onboarding na 1a vez)"
    }
    Write-Host "  Kokoro:  http://127.0.0.1:$($cfg.KokoroPort)"
    Write-Host "  Thina:   http://127.0.0.1:$($cfg.ThinaPort)/health"
    Write-Host "  Docs:    http://127.0.0.1:$($cfg.ThinaPort)/docs"
    Write-Host "  Teste:   .\.venv\Scripts\python scripts\test_app.py"
    Write-Host "  Microfone: .\test-mic.ps1`n"
}

function Stop-ThinaStack {
    $cfg = Get-StackConfig
    Write-Host "`n=== Parando servicos Thina ===" -ForegroundColor Cyan

    # Thina primeiro (depende do Kokoro)
    $step = 1
    $total = if ($cfg.HaManaged) { 3 } else { 2 }
    Write-Host "[$step/$total] thina-server"
    Stop-ManagedProcess -Name "thina" -Port $cfg.ThinaPort -RunDir $cfg.RunDir

    $step++
    Write-Host "`n[$step/$total] Kokoro TTS"
    Stop-ManagedProcess -Name "kokoro" -Port $cfg.KokoroPort -RunDir $cfg.RunDir

    if ($cfg.HaManaged) {
        $step++
        Write-Host "`n[$step/$total] Home Assistant"
        Stop-HomeAssistant $cfg
    }

    Write-Host "`n=== Stack parada ===`n" -ForegroundColor Cyan
}

function Show-ThinaStackStatus {
    $cfg = Get-StackConfig
    Write-Host "`n=== Estado da stack ===" -ForegroundColor Cyan
    $services = @()
    if ($cfg.HaManaged) {
        $services += @{
            Name   = "homeassistant"
            Port   = $cfg.HaPort
            Health = "http://127.0.0.1:$($cfg.HaPort)/"
            Docker = $true
        }
    }
    $services += @(
        @{ Name = "kokoro"; Port = $cfg.KokoroPort; Health = "http://127.0.0.1:$($cfg.KokoroPort)/voices"; Docker = $false },
        @{ Name = "thina"; Port = $cfg.ThinaPort; Health = "http://127.0.0.1:$($cfg.ThinaPort)/health"; Docker = $false }
    )

    foreach ($svc in $services) {
        $httpOk = $false
        try {
            $r = Invoke-WebRequest -Uri $svc.Health -UseBasicParsing -TimeoutSec 3
            $httpOk = $r.StatusCode -ge 200 -and $r.StatusCode -lt 400
        } catch { }

        if ($svc.Docker) {
            $dockerUp = $false
            if (Test-WslDocker $cfg) {
                $dockerUp = Test-HomeAssistantContainerRunning $cfg
            }
            $status = if ($httpOk) { "UP" } elseif ($dockerUp) { "STARTING" } else { "DOWN" }
            $color = if ($httpOk) { "Green" } elseif ($dockerUp) { "Yellow" } else { "Red" }
            Write-Host ("  {0,-14} porta {1,-5} container={2,-5} HTTP={3}" -f `
                    $svc.Name, $svc.Port, $(if ($dockerUp) { "sim" } else { "nao" }), $status) -ForegroundColor $color
        } else {
            $pidFile = Get-PidFilePath $svc.Name $cfg.RunDir
            $filePid = if (Test-Path $pidFile) { Get-Content $pidFile -Raw } else { "-" }
            $portPid = Get-ListenerPid $svc.Port
            $status = if ($httpOk) { "UP" } else { "DOWN" }
            $color = if ($httpOk) { "Green" } else { "Red" }
            Write-Host ("  {0,-14} porta {1,-5} PID(ficheiro)={2,-8} PID(porta)={3,-8} HTTP={4}" -f `
                    $svc.Name, $svc.Port, $filePid, $(if ($portPid) { $portPid } else { "-" }), $status) -ForegroundColor $color
        }
    }
    Write-Host ""
}
