param(
    [switch]$Console,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Local bootstrap used during development; a normal venv has PyInstaller installed.
$LocalPyInstaller = Join-Path $Root ".tools\pyinstaller"
if (Test-Path $LocalPyInstaller) {
    $env:PYTHONPATH = $LocalPyInstaller + ";" + $env:PYTHONPATH
}
$LocalDeps = Join-Path $Root ".deps"
if (Test-Path $LocalDeps) {
    $env:PYTHONPATH = (Join-Path $Root "src") + ";" + (Join-Path $LocalDeps "webui") + ";" + (Join-Path $LocalDeps "extra") + ";" + $env:PYTHONPATH
}

$Name = if ($Console) { "EasyExifDebug" } else { "EasyExif" }
$Mode = if ($Console) { "--console" } else { "--windowed" }
$Icon = Join-Path $Root "packaging\easyexif.ico"
$Static = (Join-Path $Root "src\easyexif\webui\static") + ";easyexif\webui\static"

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onefile", "--runtime-tmpdir", ".easyexif-runtime", $Mode,
    "--name", $Name,
    "--icon", $Icon,
    "--add-data", $Static,
    "--paths", (Join-Path $Root "src"),
    "--hidden-import", "easyexif.webui.dialog_helper",
    "--hidden-import", "proxy_tools",
    "--hidden-import", "bottle",
    "--hidden-import", "typing_extensions",
    "--hidden-import", "PIL._tkinter_finder",
    "--collect-all", "webview",
    "--collect-all", "pythonnet",
    "--collect-all", "clr_loader",
    "--collect-all", "cffi",
    "--collect-submodules", "easyexif",
    "--distpath", (Join-Path $Root "dist"),
    "--workpath", (Join-Path $Root "build\pyinstaller"),
    "--specpath", (Join-Path $Root "build"),
    (Join-Path $Root "packaging\entry.py")
)

# Development fallback: dependencies unpacked into .deps by the local bootstrap.
if (Test-Path (Join-Path $Root ".deps\webui")) {
    $arguments = $arguments[0..($arguments.Count - 2)] + @(
        "--paths", (Join-Path $Root ".deps\webui"),
        "--paths", (Join-Path $Root ".deps\extra"),
        (Join-Path $Root "packaging\entry.py")
    )
}

& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Write-Host ("Built " + (Join-Path $Root ("dist\" + $Name + ".exe")))
