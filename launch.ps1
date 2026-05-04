Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoBranch = "main"
$ModelName = "qwen2.5:1.5b"
$AppHost = if ($env:IA_PROFESOR_HOST) { $env:IA_PROFESOR_HOST } else { "127.0.0.1" }
$AppPort = if ($env:IA_PROFESOR_PORT) { [int]$env:IA_PROFESOR_PORT } else { 5000 }
$AppUrl = if ($AppHost -eq "0.0.0.0") { "http://127.0.0.1:$AppPort" } else { "http://$AppHost`:$AppPort" }
$RuntimePaths = @(
    "chat_data",
    "conversation_history.json"
)

function Write-Info($message) {
    Write-Host "[INFO] $message" -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host "[OK] $message" -ForegroundColor Green
}

function Write-WarnLine($message) {
    Write-Host "[AVISO] $message" -ForegroundColor Yellow
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Find-PythonCommand {
    $candidates = @(
        @{ Command = "py.exe"; Arguments = @("-3") },
        @{ Command = "python.exe"; Arguments = @() },
        @{ Command = "python"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (Get-Command $candidate.Command -ErrorAction SilentlyContinue) {
            return $candidate
        }
    }

    return $null
}

function Ensure-OllamaAvailable {
    if (Get-Command "ollama.exe" -ErrorAction SilentlyContinue) {
        return $true
    }

    Refresh-Path
    return $null -ne (Get-Command "ollama.exe" -ErrorAction SilentlyContinue)
}

function Ensure-OllamaRunning {
    if (-not (Ensure-OllamaAvailable)) {
        Write-WarnLine "No encontré Ollama. Sigo sin modo local; podés usar OpenAI/Gemini desde la web."
        return $false
    }

    & ollama list *> $null
    if ($LASTEXITCODE -eq 0) {
        return $true
    }

    Write-WarnLine "Ollama no estaba activo. Intentando iniciarlo..."
    try {
        Start-Process -FilePath "ollama.exe" -ArgumentList "serve" -WindowStyle Minimized | Out-Null
    }
    catch {
        Write-WarnLine "No pude iniciar Ollama automáticamente. Abrí la app de Ollama si hace falta."
    }

    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        & ollama list *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Ollama quedó listo."
            return $true
        }
    }

    Write-WarnLine "No pude conectarme a Ollama. Sigo igual; si querés modo local, abrilo manualmente después."
    return $false
}

function Ensure-Model([string]$Model) {
    $models = & ollama list 2>$null
    if ($LASTEXITCODE -eq 0 -and ($models | Select-String -SimpleMatch $Model)) {
        return
    }

    Write-Info "Falta el modelo $Model. Descargándolo..."
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
        throw "No pude descargar el modelo $Model."
    }
}

function Backup-RuntimeData {
    $backupRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ia_profesor_runtime_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $backupRoot | Out-Null

    foreach ($relativePath in $RuntimePaths) {
        $sourcePath = Join-Path $ProjectRoot $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            continue
        }

        $destinationPath = Join-Path $backupRoot $relativePath
        $destinationParent = Split-Path -Parent $destinationPath
        if ($destinationParent -and -not (Test-Path -LiteralPath $destinationParent)) {
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        }

        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
    }

    return $backupRoot
}

function Restore-RuntimeData([string]$BackupRoot) {
    foreach ($relativePath in $RuntimePaths) {
        $backupPath = Join-Path $BackupRoot $relativePath
        if (-not (Test-Path -LiteralPath $backupPath)) {
            continue
        }

        $destinationPath = Join-Path $ProjectRoot $relativePath
        $destinationParent = Split-Path -Parent $destinationPath
        if ($destinationParent -and -not (Test-Path -LiteralPath $destinationParent)) {
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        }

        Copy-Item -LiteralPath $backupPath -Destination $destinationPath -Recurse -Force
    }
}

function Update-RepoIfPossible {
    if (-not (Get-Command "git.exe" -ErrorAction SilentlyContinue)) {
        Write-WarnLine "Git no está disponible. Sigo sin actualizar el repositorio."
        return $false
    }

    $gitDir = Join-Path $ProjectRoot ".git"
    if (-not (Test-Path -LiteralPath $gitDir)) {
        Write-WarnLine "Esta carpeta no parece ser un clon git. Sigo sin actualización automática."
        return $false
    }

    $statusOutput = & git -C $ProjectRoot status --porcelain
    $hasTrackedChanges = $false
    foreach ($line in $statusOutput) {
        if ($line.Length -lt 3) {
            continue
        }

        $indexStatus = $line.Substring(0, 1)
        $worktreeStatus = $line.Substring(1, 1)
        if ($indexStatus -ne "?" -or $worktreeStatus -ne "?") {
            $hasTrackedChanges = $true
            break
        }
    }

    if ($hasTrackedChanges) {
        Write-WarnLine "Hay cambios locales versionados. Salteo la actualización automática para no romper nada."
        return $false
    }

    & git -C $ProjectRoot fetch origin $RepoBranch --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-WarnLine "No pude consultar actualizaciones remotas. Sigo con la versión local."
        return $false
    }

    $localHead = (& git -C $ProjectRoot rev-parse HEAD).Trim()
    $remoteHead = (& git -C $ProjectRoot rev-parse "origin/$RepoBranch").Trim()

    if ($localHead -eq $remoteHead) {
        return $false
    }

    $baseHead = (& git -C $ProjectRoot merge-base HEAD "origin/$RepoBranch").Trim()
    if ($baseHead -ne $localHead) {
        Write-WarnLine "La rama local no está detrás de origin/main en forma limpia. Salteo la actualización automática."
        return $false
    }

    Write-Info "Hay una actualización disponible. Aplicándola..."
    $backupRoot = Backup-RuntimeData
    try {
        & git -C $ProjectRoot pull --ff-only origin $RepoBranch
        if ($LASTEXITCODE -ne 0) {
            throw "Git no pudo actualizar con fast-forward."
        }
        Restore-RuntimeData -BackupRoot $backupRoot
        Write-Ok "Repositorio actualizado."
        return $true
    }
    catch {
        Write-WarnLine $_.Exception.Message
        Write-WarnLine "Sigo con la copia local actual."
        return $false
    }
    finally {
        if (Test-Path -LiteralPath $backupRoot) {
            Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Ensure-Venv {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    $python = Find-PythonCommand
    if (-not $python) {
        throw "No encontré Python para crear el entorno virtual. Instalalo y volvé a intentar."
    }

    Write-Info "Creando entorno virtual local..."
    & $python.Command @($python.Arguments + @("-m", "venv", (Join-Path $ProjectRoot ".venv")))
    if ($LASTEXITCODE -ne 0) {
        throw "No pude crear el entorno virtual."
    }

    return $venvPython
}

function Get-FileSha256([string]$Path) {
    if (Get-Command "Get-FileHash" -ErrorAction SilentlyContinue) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hashBytes = $sha256.ComputeHash($stream)
        }
        finally {
            $stream.Dispose()
        }

        return ([System.BitConverter]::ToString($hashBytes)).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
    }
}

function Ensure-Dependencies([string]$PythonExe) {
    $requirementsPath = Join-Path $ProjectRoot "requirements.txt"
    $stampPath = Join-Path $ProjectRoot ".venv\.requirements.sha256"
    $currentHash = Get-FileSha256 -Path $requirementsPath
    $savedHash = if (Test-Path -LiteralPath $stampPath) { (Get-Content -LiteralPath $stampPath -Raw).Trim() } else { "" }

    if ($currentHash -eq $savedHash) {
        return
    }

    Write-Info "Instalando/actualizando dependencias de Python..."
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "No pude instalar las dependencias de Python."
    }

    Set-Content -LiteralPath $stampPath -Value $currentHash -Encoding ASCII
}

function Open-BrowserSoon {
    $loadingPage = Join-Path $ProjectRoot "launch-wait.html"
    if (Test-Path -LiteralPath $loadingPage) {
        Start-Process -FilePath $loadingPage | Out-Null
        return
    }

    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-Command", "Start-Sleep -Seconds 3; Start-Process '$AppUrl'"
    ) -WindowStyle Hidden | Out-Null
}

function Ensure-FirewallRule([int]$Port) {
    try {
        $ruleName = "ia_profesor_$Port"
        $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        if (-not $existing) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
            Write-Ok "Regla de firewall creada para el puerto $Port."
        }
        else {
            Write-Ok "La regla de firewall para el puerto $Port ya existe."
        }
    }
    catch {
        Write-WarnLine "No pude verificar/crear la regla de firewall para el puerto $Port. Si tu celular no entra, abrí ese puerto manualmente o ejecutá como administrador."
    }
}

function Get-LanUrls([int]$Port) {
    $urls = @()
    try {
        $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254*' -and
                $_.PrefixOrigin -ne 'WellKnown'
            } |
            Select-Object -ExpandProperty IPAddress -Unique

        foreach ($ip in $addresses) {
            $urls += "http://$ip`:$Port"
        }
    }
    catch {
        # ignore
    }
    return $urls
}

try {
    Set-Location $ProjectRoot
    Write-Host "Iniciando ia_profesor..." -ForegroundColor Green

    $updated = Update-RepoIfPossible
    $pythonExe = Ensure-Venv
    Ensure-Dependencies -PythonExe $pythonExe
    $ollamaReady = Ensure-OllamaRunning
    if ($ollamaReady) {
        Ensure-Model -Model $ModelName
    }

    if ($updated) {
        Write-Info "La app fue actualizada antes de abrirse."
    }

    if ($AppHost -eq "0.0.0.0") {
        Ensure-FirewallRule -Port $AppPort
        $lanUrls = Get-LanUrls -Port $AppPort
        if ($lanUrls.Count -gt 0) {
            Write-Host "Acceso desde otros equipos de tu red:" -ForegroundColor Green
            foreach ($url in $lanUrls) {
                Write-Host " - $url" -ForegroundColor White
            }
        }
    }

    Write-Info "Abriendo la app web en $AppUrl"
    Open-BrowserSoon
    $env:IA_PROFESOR_HOST = $AppHost
    $env:IA_PROFESOR_PORT = "$AppPort"
    & $pythonExe (Join-Path $ProjectRoot "web_app.py")
    exit $LASTEXITCODE
}
catch {
    Write-WarnLine $_.Exception.Message
    Write-Host ""
    Read-Host "Presioná Enter para cerrar"
    exit 1
}
