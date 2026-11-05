param(
    [string]$InstallDir = 'C:\ncs'
)

# Run in a normal PowerShell window. Installs the SDK and builds source only.
# This script never flashes, erases, or connects to the watch.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$firmwareRoot = Join-Path $projectRoot 'fw'
$nrfutilPath = Join-Path $projectRoot 'tools\nordic\nrfutil.exe'
$env:NRFUTIL_HOME = Join-Path $projectRoot 'tools\nordic\home'

if (-not (Test-Path -LiteralPath $nrfutilPath)) {
    throw "Nordic installer is missing: $nrfutilPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $firmwareRoot 'app\src\hpi_research.c'))) {
    throw 'Modified firmware source is missing.'
}

Write-Host 'Installing Nordic SDK v3.4.0 and its matching toolchain. This can take a while.'
& $nrfutilPath sdk-manager install v3.4.0 --install-dir $InstallDir
if ($LASTEXITCODE -ne 0) {
    throw 'Nordic SDK installation failed. Keep the error output; no build or watch update was attempted.'
}

$sdkRoot = Join-Path $InstallDir 'v3.4.0'
if (-not (Test-Path -LiteralPath (Join-Path $sdkRoot '.west'))) {
    throw "Expected SDK workspace not found at $sdkRoot. Check the installation output for its actual path."
}

Write-Host 'Checking West in the Nordic toolchain environment...'
& $nrfutilPath sdk-manager toolchain launch --ncs-version v3.4.0 --install-dir $InstallDir --chdir $sdkRoot -- west --version
if ($LASTEXITCODE -ne 0) { throw 'West/toolchain check failed.' }

Write-Host 'Building the modified HealthyPi Move firmware...'
& $nrfutilPath sdk-manager toolchain launch --ncs-version v3.4.0 --install-dir $InstallDir --chdir $sdkRoot -- python (Join-Path $firmwareRoot 'tools\build_research.py') --sdk-root $sdkRoot --pristine
if ($LASTEXITCODE -ne 0) { throw 'Firmware build failed. Keep the error output so the source/build configuration can be fixed.' }

$dfuPath = Join-Path $firmwareRoot 'build\dfu_application.zip'
if (-not (Test-Path -LiteralPath $dfuPath)) {
    throw 'Build command succeeded but the expected DFU package was not found. Inspect the build artifacts.'
}
Write-Host "Build finished. Generated firmware package: $dfuPath"
Write-Host 'The watch has NOT been updated. Hardware testing is still required.'
