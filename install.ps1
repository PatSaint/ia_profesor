Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/PatSaint/ia_profesor"
$DefaultFolderName = "ia_profesor"
$ModelName = "qwen2.5:1.5b"

function Write-Info($message) {
    Write-Host "[INFO] $message" -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host "[OK] $message" -ForegroundColor Green
}

function Write-WarnLine($message) {
    Write-Host "[AVISO] $message" -ForegroundColor Yellow
}

function Write-Step($message) {
    Write-Host "`n=== $message ===" -ForegroundColor Magenta
}

function Pause-And-Exit([int]$Code = 1) {
    Write-Host ""
    Read-Host "Presioná Enter para cerrar"
    exit $Code
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Test-CommandExists([string]$CommandName) {
    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
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

function Install-WithWinget([string]$WingetId, [string]$DisplayName) {
    if (-not (Test-CommandExists "winget.exe")) {
        Write-WarnLine "No encontré winget para instalar $DisplayName automáticamente."
        return $false
    }

    $answer = Read-Host "Falta $DisplayName. ¿Querés que intente instalarlo con winget? (S/N)"
    if ($answer -notmatch '^(s|si|sí|y|yes)$') {
        return $false
    }

    Write-Info "Intentando instalar $DisplayName con winget..."
    & winget install --id $WingetId -e --accept-package-agreements --accept-source-agreements
    $success = $LASTEXITCODE -eq 0
    Refresh-Path
    return $success
}

function Ensure-Git {
    if (Test-CommandExists "git.exe") {
        Write-Ok "Git ya está disponible."
        return
    }

    if (-not (Install-WithWinget -WingetId "Git.Git" -DisplayName "Git")) {
        Write-WarnLine "Instalá Git desde https://git-scm.com/download/win y volvé a ejecutar este instalador."
        Pause-And-Exit 1
    }

    if (-not (Test-CommandExists "git.exe")) {
        Write-WarnLine "Git se instaló, pero esta ventana todavía no lo detecta. Cerrá y volvé a ejecutar el instalador."
        Pause-And-Exit 1
    }

    Write-Ok "Git listo."
}

function Ensure-Python {
    $python = Find-PythonCommand
    if ($python) {
        Write-Ok "Python ya está disponible."
        return $python
    }

    if (-not (Install-WithWinget -WingetId "Python.Python.3.11" -DisplayName "Python 3.11")) {
        Write-WarnLine "Instalá Python desde https://www.python.org/downloads/windows/ y activá la opción Add Python to PATH."
        Pause-And-Exit 1
    }

    $python = Find-PythonCommand
    if (-not $python) {
        Write-WarnLine "Python se instaló, pero esta ventana todavía no lo detecta. Cerrá y volvé a ejecutar el instalador."
        Pause-And-Exit 1
    }

    Write-Ok "Python listo."
    return $python
}

function Ensure-Ollama {
    if (Test-CommandExists "ollama.exe") {
        Write-Ok "Ollama ya está disponible."
        return $true
    }

    $answer = Read-Host "Ollama no está instalado. ¿Querés instalarlo ahora para usar modo local? (S/N)"
    if ($answer -notmatch '^(s|si|sí|y|yes)$') {
        Write-WarnLine "Seguimos sin Ollama. Después podés usar OpenAI/Gemini o instalar Ollama manualmente si querés modo local."
        return $false
    }

    if (-not (Install-WithWinget -WingetId "Ollama.Ollama" -DisplayName "Ollama")) {
        Write-WarnLine "No pude instalar Ollama automáticamente. Seguimos sin modo local por ahora."
        return $false
    }

    if (-not (Test-CommandExists "ollama.exe")) {
        Write-WarnLine "Ollama se instaló, pero esta ventana todavía no lo detecta. Podés cerrar y reintentar luego si querés usar modo local."
        return $false
    }

    Write-Ok "Ollama listo."
    return $true
}

function Ensure-OllamaRunning {
    Write-Info "Verificando servicio de Ollama..."
    & ollama list *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Ollama responde correctamente."
        return $true
    }

    Write-WarnLine "Ollama no está respondiendo. Voy a intentar iniciarlo."
    try {
        Start-Process -FilePath "ollama.exe" -ArgumentList "serve" -WindowStyle Minimized | Out-Null
    }
    catch {
        Write-WarnLine "No pude iniciar Ollama automáticamente. Abrí la app de Ollama manualmente si sigue fallando."
    }

    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        & ollama list *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Ollama quedó funcionando."
            return $true
        }
    }

    Write-WarnLine "No pude confirmar que Ollama esté funcionando. Abrí Ollama manualmente y volvé a ejecutar el instalador."
    return $false
}

function Ensure-Model([string]$Model) {
    Write-Info "Verificando modelo $Model ..."
    $models = & ollama list 2>$null
    if ($LASTEXITCODE -eq 0 -and ($models | Select-String -SimpleMatch $Model)) {
        Write-Ok "El modelo $Model ya existe."
        return
    }

    Write-Info "Descargando modelo $Model ... esto puede tardar un poco."
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
        Write-WarnLine "No pude descargar el modelo $Model. Revisá Ollama y tu conexión a internet."
        Pause-And-Exit 1
    }

    Write-Ok "Modelo $Model listo."
}

function New-DesktopShortcut([string]$TargetPath, [string]$WorkingDirectory) {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "Iniciar ia_profesor.lnk"
    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
    $shortcut.Save()
    Write-Ok "Acceso directo creado en el escritorio: Iniciar ia_profesor"
}

try {
    Clear-Host
    Write-Host "Instalador de ia_profesor" -ForegroundColor Green
    Write-Host "Este asistente va a clonar el proyecto, preparar Python y dejarte un acceso directo en el escritorio.`n"

    Write-Step "Chequeando requisitos"
    Ensure-Git
    $python = Ensure-Python
    $ollamaInstalled = Ensure-Ollama

    Write-Step "Elegí dónde instalar"
    $defaultParent = (Get-Location).Path
    $parentInput = Read-Host "Carpeta base de instalación [`$default: $defaultParent]"
    $installParent = if ([string]::IsNullOrWhiteSpace($parentInput)) { $defaultParent } else { $parentInput.Trim('"') }

    if (-not (Test-Path -LiteralPath $installParent)) {
        Write-WarnLine "La carpeta base no existe: $installParent"
        Pause-And-Exit 1
    }

    $folderInput = Read-Host "Nombre de la carpeta nueva [`$default: $DefaultFolderName]"
    $folderName = if ([string]::IsNullOrWhiteSpace($folderInput)) { $DefaultFolderName } else { $folderInput.Trim() }
    $installPath = Join-Path $installParent $folderName

    if (Test-Path -LiteralPath $installPath) {
        Write-WarnLine "La carpeta destino ya existe: $installPath"
        Write-WarnLine "Elegí otra carpeta o borrala manualmente antes de continuar."
        Pause-And-Exit 1
    }

    Write-Step "Clonando repositorio"
    & git clone --branch main --single-branch $RepoUrl "$installPath"
    if ($LASTEXITCODE -ne 0) {
        Write-WarnLine "Falló el clonado del repositorio."
        Pause-And-Exit 1
    }
    Write-Ok "Repositorio clonado en $installPath"

    Write-Step "Preparando entorno Python"
    $venvPath = Join-Path $installPath ".venv"
    & $python.Command @($python.Arguments + @("-m", "venv", $venvPath))
    if ($LASTEXITCODE -ne 0) {
        Write-WarnLine "No pude crear el entorno virtual."
        Pause-And-Exit 1
    }

    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $installPath "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-WarnLine "Falló la instalación de dependencias de Python."
        Pause-And-Exit 1
    }
    Write-Ok "Entorno virtual y dependencias listos."

    if ($ollamaInstalled) {
        Write-Step "Preparando Ollama"
        if (Ensure-OllamaRunning) {
            Ensure-Model -Model $ModelName
        }
    }

    Write-Step "Creando acceso directo"
    $launcherPath = Join-Path $installPath "Iniciar ia_profesor.bat"
    if (-not (Test-Path -LiteralPath $launcherPath)) {
        Write-WarnLine "No encontré el launcher esperado: $launcherPath"
        Pause-And-Exit 1
    }

    New-DesktopShortcut -TargetPath $launcherPath -WorkingDirectory $installPath

    Write-Host ""
    Write-Ok "Instalación terminada."
    Write-Host "Podés iniciar la app desde el acceso directo 'Iniciar ia_profesor' en el escritorio." -ForegroundColor White
    Pause-And-Exit 0
}
catch {
    Write-WarnLine $_.Exception.Message
    Write-WarnLine "Si PowerShell te bloquea por políticas de ejecución, usá install.bat o ejecutá: powershell -ExecutionPolicy Bypass -File .\install.ps1"
    Pause-And-Exit 1
}
