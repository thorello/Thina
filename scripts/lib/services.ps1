# Funcoes partilhadas para subir/parar a stack Thina (Kokoro + thina-server).
# Uso: . "$PSScriptRoot\lib\services.ps1"

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

    return [PSCustomObject]@{
        Root       = $root
        RunDir     = Get-RunDir $root
        KokoroDir  = $kokoroDir
        ThinaPort  = $thinaPort
        KokoroPort = $kokoroPort
        ThinaPy    = if (Test-Path $thinaVenv) { $thinaVenv } else { "python" }
        KokoroPy   = if (Test-Path $kokoroVenv) { $kokoroVenv } else { "python" }
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
    Write-Host "Thina:  :$($cfg.ThinaPort)`n"

    if (-not (Test-Path $cfg.KokoroDir)) {
        throw "Pasta Kokoro nao encontrada: $($cfg.KokoroDir). Defina KOKORO_DIR no .env"
    }
    if (-not (Test-Path (Join-Path $cfg.KokoroDir "src\app.py"))) {
        throw "src\app.py nao encontrado em $($cfg.KokoroDir)"
    }

    # 1) Kokoro (TTS)
    Write-Host "[1/2] Kokoro TTS"
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

    # 2) Thina
    Write-Host "`n[2/2] thina-server"
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
    Write-Host "  Kokoro:  http://127.0.0.1:$($cfg.KokoroPort)"
    Write-Host "  Thina:   http://127.0.0.1:$($cfg.ThinaPort)/health"
    Write-Host "  Docs:    http://127.0.0.1:$($cfg.ThinaPort)/docs"
    Write-Host "  Teste:   .\.venv\Scripts\python scripts\test_app.py"
    Write-Host "  Microfone: .\test-mic.ps1`n"
    Write-Host "Home Assistant nao e gerido por estes scripts (corre a parte).`n"
}

function Stop-ThinaStack {
    $cfg = Get-StackConfig
    Write-Host "`n=== Parando servicos Thina ===" -ForegroundColor Cyan

    # Thina primeiro (depende do Kokoro)
    Write-Host "[1/2] thina-server"
    Stop-ManagedProcess -Name "thina" -Port $cfg.ThinaPort -RunDir $cfg.RunDir

    Write-Host "`n[2/2] Kokoro TTS"
    Stop-ManagedProcess -Name "kokoro" -Port $cfg.KokoroPort -RunDir $cfg.RunDir

    Write-Host "`n=== Servicos locais parados ===`n" -ForegroundColor Cyan
}

function Show-ThinaStackStatus {
    $cfg = Get-StackConfig
    Write-Host "`n=== Estado da stack ===" -ForegroundColor Cyan
    foreach ($svc in @(
            @{ Name = "kokoro"; Port = $cfg.KokoroPort; Health = "http://127.0.0.1:$($cfg.KokoroPort)/voices" },
            @{ Name = "thina"; Port = $cfg.ThinaPort; Health = "http://127.0.0.1:$($cfg.ThinaPort)/health" }
        )) {
        $pidFile = Get-PidFilePath $svc.Name $cfg.RunDir
        $filePid = if (Test-Path $pidFile) { Get-Content $pidFile -Raw } else { "-" }
        $portPid = Get-ListenerPid $svc.Port
        $httpOk = $false
        try {
            $r = Invoke-WebRequest -Uri $svc.Health -UseBasicParsing -TimeoutSec 3
            $httpOk = $r.StatusCode -eq 200
        } catch { }
        $status = if ($httpOk) { "UP" } else { "DOWN" }
        $color = if ($httpOk) { "Green" } else { "Red" }
        Write-Host ("  {0,-8} porta {1,-5} PID(ficheiro)={2,-8} PID(porta)={3,-8} HTTP={4}" -f `
                $svc.Name, $svc.Port, $filePid, $(if ($portPid) { $portPid } else { "-" }), $status) -ForegroundColor $color
    }
    Write-Host ""
}
