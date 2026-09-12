param(
    [Parameter(Mandatory = $true)][string]$PackageDir
)

$exe = Join-Path ([System.IO.Path]::GetFullPath($PackageDir)) "GMES.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "Packaged executable not found: $exe" }

$originalPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot;$env:SystemRoot\System32"
    Push-Location ([System.IO.Path]::GetFullPath($PackageDir))
    & $exe version
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $exe login --help
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $exe run --help
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $exe data --help
    exit $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PATH = $originalPath
}
