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

    $wslDistro = $env["WSL_DISTRO"]
    if (-not $wslDistro) { $wslDistro = "Ubuntu" }

    $uiPort = 5173
    if ($env["THINA_UI_PORT"]) { [void][int]::TryParse($env["THINA_UI_PORT"], [ref]$uiPort) }

    return [PSCustomObject]@{
        Root          = $root
        RunDir        = Get-RunDir $root
        KokoroDir     = $kokoroDir
        ThinaPort     = $thinaPort
        KokoroPort    = $kokoroPort
        UiPort        = $uiPort
        HaPort        = $haPort
        HaManaged     = $haManaged
        HaComposeDir  = Join-Path $root "scripts\ha"
        HaContainer   = "thina-homeassistant"
        WslDistro     = $wslDistro
        ThinaPy       = if (Test-Path $thinaVenv) { $thinaVenv } else { "python" }
        KokoroPy      = if (Test-Path $kokoroVenv) { $kokoroVenv } else { "python" }
    }
}

function Get-StackServiceCount {
    param([object]$Cfg)
    return $(if ($Cfg.HaManaged) { 4 } else { 3 })
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
        [string[]]$Command,
        [int]$TimeoutSec = 0
    )
    $wslBase = Get-WslExeArgs $Cfg
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    if ($TimeoutSec -gt 0) {
        $job = Start-Job -ScriptBlock {
            param($Base, $Cmd)
            $ErrorActionPreference = "Continue"
            $o = & wsl @Base @Cmd 2>&1 | ForEach-Object { "$_" }
            [PSCustomObject]@{ Exit = $LASTEXITCODE; Out = $o }
        } -ArgumentList (,$wslBase), (,$Command)

        $done = Wait-Job $job -Timeout $TimeoutSec
        if (-not $done) {
            Stop-Job $job -Force -ErrorAction SilentlyContinue
            Remove-Job $job -Force -ErrorAction SilentlyContinue
            $ErrorActionPreference = $prevEap
            throw "Comando WSL expirou (${TimeoutSec}s): $($Command -join ' ')"
        }
        $result = Receive-Job $job
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        $exit = $result.Exit
        $out = $result.Out
    } else {
        $out = & wsl @wslBase @Command 2>&1 | ForEach-Object { "$_" }
        $exit = $LASTEXITCODE
    }

    $ErrorActionPreference = $prevEap
    if ($exit -ne 0) {
        throw "Comando WSL falhou (exit $exit): $($Command -join ' ') | $out"
    }
    return $out
}

function Invoke-WslDocker {
    param(
        [object]$Cfg,
        [string[]]$DockerArgs,
        [int]$TimeoutSec = 0
    )
    $dockerCmd = @("docker") + @($DockerArgs)
    return Invoke-WslCommand -Cfg $Cfg -Command $dockerCmd -TimeoutSec $TimeoutSec
}

function Test-WslDocker {
    param(
        [object]$Cfg,
        [int]$TimeoutSec = 90
    )
    try {
        Write-Host "  Verificando Docker no WSL ($($Cfg.WslDistro), ate ${TimeoutSec}s) ..."
        Invoke-WslDocker -Cfg $Cfg -DockerArgs @("version", "--format", "{{.Server.Version}}") -TimeoutSec $TimeoutSec | Out-Null
        return $true
    } catch {
        Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkYellow
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

function Restart-HomeAssistantContainers {
    param([object]$Cfg)
    $restarted = $false
    foreach ($name in @($Cfg.HaContainer, "homeassistant")) {
        try {
            $running = Invoke-WslDocker -Cfg $Cfg -DockerArgs @(
                "ps", "--filter", "name=^/${name}$", "--filter", "status=running", "-q"
            )
            if (($running | Out-String).Trim()) {
                Invoke-WslDocker -Cfg $Cfg -DockerArgs @("restart", $name) | Out-Null
                Write-Host "  [homeassistant] container $name reiniciado" -ForegroundColor Green
                $restarted = $true
            }
        } catch { }
    }
    return $restarted
}

function Start-HomeAssistant {
    param(
        [object]$Cfg,
        [switch]$ForceRestart
    )
    if (-not $Cfg.HaManaged) {
        Write-Host "  [homeassistant] HOME_ASSISTANT_MANAGED=false - ignorado" -ForegroundColor DarkGray
        return
    }
    if (-not (Test-WslDocker $Cfg)) {
        Write-Host "  AVISO: Docker/WSL indisponivel ou lento - HA ignorado; Kokoro e Thina seguem." -ForegroundColor Yellow
        Write-Host "  Dica: wsl --shutdown; confira WSL_DISTRO no .env; ou HOME_ASSISTANT_MANAGED=false" -ForegroundColor DarkGray
        return
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

    if ($ForceRestart) {
        if (Restart-HomeAssistantContainers $Cfg) {
            Write-Host "  Aguardando $haUrl apos reinicio do container ..."
            if (Wait-HttpOk $haUrl 120) {
                Write-Host "  Home Assistant OK" -ForegroundColor Green
            } else {
                Write-Host "  AVISO: HA ainda nao respondeu apos restart. Veja: wsl docker logs homeassistant" -ForegroundColor Yellow
            }
            return
        }
    } elseif (Test-HomeAssistantHttp $Cfg) {
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

    Write-Host "  Aguardando $haUrl - ate 60s, depois Kokoro/Thina sobem mesmo sem HA ..."
    if (-not (Wait-HttpOk $haUrl 60)) {
        Write-Host "  AVISO: HA ainda nao respondeu. Veja: wsl docker logs homeassistant" -ForegroundColor Yellow
    } else {
        Write-Host "  Home Assistant OK" -ForegroundColor Green
    }
}

function Stop-HomeAssistant {
    param(
        [object]$Cfg,
        [switch]$Force
    )
    if (-not $Cfg.HaManaged) {
        Write-Host "  [homeassistant] HOME_ASSISTANT_MANAGED=false - ignorado" -ForegroundColor DarkGray
        return
    }
    if (-not (Test-WslDocker $Cfg)) {
        Write-Host "  [homeassistant] Docker/WSL indisponivel" -ForegroundColor DarkGray
        return
    }

    $stopped = $false
    foreach ($name in @($Cfg.HaContainer, "homeassistant")) {
        try {
            $running = Invoke-WslDocker -Cfg $Cfg -DockerArgs @(
                "ps", "--filter", "name=^/${name}$", "--filter", "status=running", "-q"
            )
            if (($running | Out-String).Trim()) {
                Invoke-WslDocker -Cfg $Cfg -DockerArgs @("stop", $name) | Out-Null
                Write-Host "  [homeassistant] container $name parado" -ForegroundColor Green
                $stopped = $true
            }
        } catch { }
    }

    if (-not $stopped -or -not $Force) {
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
                Write-Host "  [homeassistant] compose down ($($Cfg.HaContainer))" -ForegroundColor Green
                $stopped = $true
            }
        } catch {
            Invoke-WslDocker -Cfg $Cfg -DockerArgs @("rm", "-f", $Cfg.HaContainer) 2>$null | Out-Null
            $stopped = $true
        }
    }

    if (-not $stopped) {
        Write-Host "  [homeassistant] nao estava em execucao" -ForegroundColor DarkGray
    }
}

function Get-PidFilePath {
    param([string]$Name, [string]$RunDir)
    return Join-Path $RunDir "$Name.pid"
}

function Get-ListenerPids {
    param([int]$Port)
    $pids = [System.Collections.Generic.HashSet[int]]::new()
    $lines = netstat -ano 2>$null | Select-String ":\s*$Port\s+.*LISTENING"
    foreach ($line in $lines) {
        if ($line -match '\s+(\d+)\s*$') {
            [void]$pids.Add([int]$Matches[1])
        }
    }
    return @($pids)
}

function Get-ListenerPid {
    param([int]$Port)
    $all = Get-ListenerPids $Port
    if ($all.Count -gt 0) { return $all[0] }
    return $null
}

function Stop-PortListeners {
    param(
        [int]$Port,
        [string]$Label,
        [string]$PortProcessPattern = "",
        [switch]$AnyProcess
    )
    if ($Port -le 0) { return $false }
    $killed = $false
    foreach ($portPid in (Get-ListenerPids $Port)) {
        if (-not (Test-ProcessAlive $portPid)) { continue }
        $proc = Get-Process -Id $portPid -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        $ok = $AnyProcess
        if (-not $ok -and $PortProcessPattern) {
            $ok = $proc.ProcessName -match $PortProcessPattern
        }
        if (-not $ok) { continue }
        Stop-Process -Id $portPid -Force -ErrorAction SilentlyContinue
        Write-Host "  [$Label] porta $Port liberada (PID $portPid $($proc.ProcessName))" -ForegroundColor Green
        $killed = $true
    }
    return $killed
}

function Wait-ServicePortsFree {
    param(
        [int[]]$Ports,
        [int]$TimeoutSec = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $busy = @($Ports | Where-Object { $_ -gt 0 -and (Get-ListenerPids $_).Count -gt 0 })
        if (-not $busy) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
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
        [string]$Executable,
        [string[]]$Arguments,
        [string]$RunDir,
        [int]$ListenPort = 0,
        [string]$PortProcessPattern = "",
        [switch]$ForceRestart
    )
    $pidFile = Get-PidFilePath $Name $RunDir
    if ($ForceRestart) {
        if (Test-Path $pidFile) {
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
        if ($ListenPort -gt 0) {
            Stop-PortListeners -Port $ListenPort -Label $Name -PortProcessPattern $PortProcessPattern -AnyProcess:(-not $PortProcessPattern)
            Start-Sleep -Milliseconds 500
        }
    } else {
        if (Test-Path $pidFile) {
            $oldPid = [int](Get-Content $pidFile -Raw)
            if (Test-ProcessAlive $oldPid) {
                Write-Host "  [$Name] ja em execucao (PID $oldPid)" -ForegroundColor Yellow
                return $oldPid
            }
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
        if ($ListenPort -gt 0 -and (Get-ListenerPid $ListenPort)) {
            Write-Host "  [$Name] porta $ListenPort em uso - ignorado (use restart para reiniciar)" -ForegroundColor Yellow
            return $null
        }
    }

    $outLog = Join-Path $RunDir "$Name.stdout.log"
    $errLog = Join-Path $RunDir "$Name.stderr.log"

    $proc = Start-Process `
        -FilePath $Executable `
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

function Ensure-ThinaUiDependencies {
    param([object]$Cfg)
    $uiDir = Join-Path $cfg.Root "ui"
    if (Test-Path (Join-Path $uiDir "node_modules")) { return }
    $npm = (Get-Command npm -ErrorAction Stop).Source
    Write-Host "  [thina-ui] npm install em ui/ (primeira vez) ..."
    & $npm install --prefix $uiDir --no-fund --no-audit 2>&1 | ForEach-Object { "  $_" } | Write-Host
    if ($LASTEXITCODE -ne 0) {
        throw "npm install em ui/ falhou (exit $LASTEXITCODE)"
    }
}

function Start-ThinaUiDev {
    param(
        [object]$Cfg,
        [switch]$ForceRestart
    )
    $uiUrl = "http://127.0.0.1:$($Cfg.UiPort)/ui/"
    if (-not $ForceRestart -and (Wait-HttpOk $uiUrl 5 1)) {
        Write-Host "  [thina-ui] ja responde em $uiUrl" -ForegroundColor Yellow
        return
    }

    Ensure-ThinaUiDependencies $Cfg
    $npm = (Get-Command npm -ErrorAction Stop).Source
    Start-ManagedProcess `
        -Name "thina-ui" `
        -WorkingDirectory $Cfg.Root `
        -Executable $npm `
        -Arguments @("run", "dev") `
        -RunDir $Cfg.RunDir `
        -ListenPort $Cfg.UiPort `
        -PortProcessPattern "node" `
        -ForceRestart:$ForceRestart | Out-Null

    Write-Host "  Aguardando $uiUrl ..."
    if (-not (Wait-HttpOk $uiUrl 90)) {
        Write-Host "  AVISO: Vite nao respondeu a tempo. Veja data\run\thina-ui.stderr.log" -ForegroundColor Yellow
    } else {
        Write-Host "  Painel UI OK" -ForegroundColor Green
    }
}

function Stop-ManagedProcess {
    param(
        [string]$Name,
        [int]$Port,
        [string]$RunDir,
        [string]$PortProcessPattern = "python",
        [switch]$Force
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

    if ($Port -gt 0) {
        if (Stop-PortListeners -Port $Port -Label $Name -PortProcessPattern $PortProcessPattern -AnyProcess:$Force) {
            $stopped = $true
        }
    }

    if (-not $stopped) {
        Write-Host "  [$Name] nao estava em execucao" -ForegroundColor DarkGray
    }
}

function Start-ThinaStack {
    param([switch]$ForceRestart)

    $cfg = Get-StackConfig
    $total = Get-StackServiceCount $cfg
    Write-Host "`n=== Subindo servicos Thina ===" -ForegroundColor Cyan
    Write-Host "Raiz: $($cfg.Root)"
    Write-Host "Kokoro: $($cfg.KokoroDir) :$($cfg.KokoroPort)"
    Write-Host "Thina:  :$($cfg.ThinaPort)"
    Write-Host "UI:     http://127.0.0.1:$($cfg.UiPort)/ui/ (npm run dev)"
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
    $step = 1
    if ($cfg.HaManaged) {
        Write-Host "[$step/$total] Home Assistant"
        Start-HomeAssistant $cfg -ForceRestart:$ForceRestart
        $step++
    }

    # 2) Kokoro (TTS)
    Write-Host "`n[$step/$total] Kokoro TTS"
    Start-ManagedProcess `
        -Name "kokoro" `
        -WorkingDirectory $cfg.KokoroDir `
        -Executable $cfg.KokoroPy `
        -Arguments @("src\app.py") `
        -RunDir $cfg.RunDir `
        -ListenPort $cfg.KokoroPort `
        -PortProcessPattern "python" `
        -ForceRestart:$ForceRestart | Out-Null
    $step++

    $kokoroHealth = "http://127.0.0.1:$($cfg.KokoroPort)/voices"
    Write-Host "  Aguardando $kokoroHealth ..."
    if (-not (Wait-HttpOk $kokoroHealth 120)) {
        Write-Host "  AVISO: Kokoro nao respondeu a tempo. Veja data\run\kokoro.stderr.log" -ForegroundColor Yellow
    } else {
        Write-Host "  Kokoro OK" -ForegroundColor Green
    }

    # 3) Thina
    Write-Host "`n[$step/$total] thina-server"
    Start-ManagedProcess `
        -Name "thina" `
        -WorkingDirectory $cfg.Root `
        -Executable $cfg.ThinaPy `
        -Arguments @("main.py") `
        -RunDir $cfg.RunDir `
        -ListenPort $cfg.ThinaPort `
        -PortProcessPattern "python" `
        -ForceRestart:$ForceRestart | Out-Null

    $thinaHealth = "http://127.0.0.1:$($cfg.ThinaPort)/health"
    Write-Host "  Aguardando $thinaHealth ..."
    if (-not (Wait-HttpOk $thinaHealth 60)) {
        Write-Host "  AVISO: Thina nao respondeu a tempo. Veja data\run\thina.stderr.log" -ForegroundColor Yellow
    } else {
        Write-Host "  Thina OK" -ForegroundColor Green
    }
    $step++

    # 4) Painel Vite (npm run dev)
    Write-Host "`n[$step/$total] Painel UI (npm run dev)"
    Start-ThinaUiDev $cfg -ForceRestart:$ForceRestart

    Write-Host "`n=== Stack pronta ===" -ForegroundColor Cyan
    if ($cfg.HaManaged) {
        Write-Host "  HA:      http://127.0.0.1:$($cfg.HaPort) (onboarding na 1a vez)"
    }
    Write-Host "  Kokoro:  http://127.0.0.1:$($cfg.KokoroPort)"
    Write-Host "  Thina:   http://127.0.0.1:$($cfg.ThinaPort)/health"
    Write-Host "  UI:      http://127.0.0.1:$($cfg.UiPort)/ui/"
    Write-Host "  Docs:    http://127.0.0.1:$($cfg.ThinaPort)/docs"
    Write-Host "  Teste:   .\.venv\Scripts\python scripts\test_app.py"
    Write-Host "  Microfone: .\test-mic.ps1`n"
}

function Stop-ThinaStack {
    param([switch]$Force)

    $cfg = Get-StackConfig
    $total = Get-StackServiceCount $cfg
    Write-Host "`n=== Parando servicos Thina ===" -ForegroundColor Cyan

    $step = 1
    Write-Host "[$step/$total] Painel UI (Vite)"
    Stop-ManagedProcess -Name "thina-ui" -Port $cfg.UiPort -RunDir $cfg.RunDir -PortProcessPattern "node" -Force:$Force

    $step++
    Write-Host "`n[$step/$total] thina-server"
    Stop-ManagedProcess -Name "thina" -Port $cfg.ThinaPort -RunDir $cfg.RunDir -Force:$Force

    $step++
    Write-Host "`n[$step/$total] Kokoro TTS"
    Stop-ManagedProcess -Name "kokoro" -Port $cfg.KokoroPort -RunDir $cfg.RunDir -Force:$Force

    if ($cfg.HaManaged) {
        $step++
        Write-Host "`n[$step/$total] Home Assistant"
        Stop-HomeAssistant $cfg -Force:$Force
    }

    Write-Host "`n=== Stack parada ===`n" -ForegroundColor Cyan
}

function Restart-ThinaStack {
    $cfg = Get-StackConfig
    Write-Host "`n=== Reiniciando stack Thina ===" -ForegroundColor Cyan
    Stop-ThinaStack -Force
    if (-not (Wait-ServicePortsFree -Ports @($cfg.UiPort, $cfg.ThinaPort, $cfg.KokoroPort) -TimeoutSec 25)) {
        Write-Host "  AVISO: alguma porta ainda ocupada; tentando subir mesmo assim ..." -ForegroundColor Yellow
    }
    Start-ThinaStack -ForceRestart
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
        @{ Name = "thina"; Port = $cfg.ThinaPort; Health = "http://127.0.0.1:$($cfg.ThinaPort)/health"; Docker = $false },
        @{ Name = "thina-ui"; Port = $cfg.UiPort; Health = "http://127.0.0.1:$($cfg.UiPort)/ui/"; Docker = $false }
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
