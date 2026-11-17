param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
    }
    $buildPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    & $buildPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw "Could not initialize pip." }
    & $buildPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & $buildPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed. Build stopped." }
    & $buildPython -m PyInstaller --noconfirm --clean PDFUnlock.spec
    if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }

    # Run the standalone EXE with Python and package environment variables removed.
    $reportDir = Join-Path $projectRoot ("build\smoke-" + [guid]::NewGuid().ToString("N"))
    $savedPath = $env:PATH
    $savedPythonPath = $env:PYTHONPATH
    $savedPythonHome = $env:PYTHONHOME
    $savedQtPlatform = $env:QT_QPA_PLATFORM
    $savedQtPluginPath = $env:QT_PLUGIN_PATH
    $savedQtPlatformPluginPath = $env:QT_QPA_PLATFORM_PLUGIN_PATH
    $portableDir = Join-Path ([System.IO.Path]::GetTempPath()) ("PDFUnlock-portable-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $portableDir | Out-Null
    $portableExe = Join-Path $portableDir "PDFUnlock.exe"
    Copy-Item -LiteralPath "dist\PDFUnlock.exe" -Destination $portableExe
    try {
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:PYTHONPATH = $null
        $env:PYTHONHOME = $null
        $env:QT_QPA_PLATFORM = $null
        $env:QT_PLUGIN_PATH = $null
        $env:QT_QPA_PLATFORM_PLUGIN_PATH = $null
        $process = Start-Process -FilePath $portableExe -WorkingDirectory $portableDir -ArgumentList @("--self-test", ('"' + $reportDir + '"')) -PassThru -WindowStyle Hidden
        if (-not $process.WaitForExit(60000)) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null
            throw "Packaged EXE smoke test timed out."
        }
        $report = Get-Content -LiteralPath (Join-Path $reportDir "self-test.json") -Raw | ConvertFrom-Json
        if ($process.ExitCode -ne 0) { throw "Packaged EXE smoke test failed: $($report.error)" }
        if (-not $report.ok -or -not $report.frozen) { throw "Invalid smoke test report." }
    } finally {
        $env:PATH = $savedPath
        $env:PYTHONPATH = $savedPythonPath
        $env:PYTHONHOME = $savedPythonHome
        $env:QT_QPA_PLATFORM = $savedQtPlatform
        $env:QT_PLUGIN_PATH = $savedQtPluginPath
        $env:QT_QPA_PLATFORM_PLUGIN_PATH = $savedQtPlatformPluginPath
        Remove-Item -LiteralPath $portableExe -ErrorAction SilentlyContinue
        if (-not (Get-ChildItem -LiteralPath $portableDir -Force)) {
            Remove-Item -LiteralPath $portableDir -ErrorAction SilentlyContinue
        }
    }
    Get-FileHash -LiteralPath "dist\PDFUnlock.exe" -Algorithm SHA256 | ForEach-Object {
        "$($_.Hash.ToLower())  PDFUnlock.exe" | Set-Content -LiteralPath "dist\PDFUnlock.exe.sha256" -Encoding ascii
    }
    Write-Host "Ready: $projectRoot\dist\PDFUnlock.exe"
    Write-Host "Smoke test: $reportDir\self-test.json"
} finally {
    Pop-Location
}
