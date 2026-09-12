param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\dist"),
    [string]$WorkDir = (Join-Path $PSScriptRoot "..\build\pyinstaller")
)

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$entry = Join-Path $repo "packaging\entrypoint.py"
$dist = [System.IO.Path]::GetFullPath($OutputDir)
$work = [System.IO.Path]::GetFullPath($WorkDir)

python -m PyInstaller --noconfirm --clean --onedir --name GMES `
    --paths (Join-Path $repo "src") --distpath $dist --workpath $work `
    --specpath $work $entry
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output (Join-Path $dist "GMES\GMES.exe")
