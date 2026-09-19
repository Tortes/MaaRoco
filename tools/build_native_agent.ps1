param(
    [string]$InstallRoot = (Join-Path $PSScriptRoot "../install"),
    [string]$SdkRoot = (Join-Path $PSScriptRoot "../deps"),
    [string]$BuildRoot = (Join-Path $PSScriptRoot "../build/native-agent"),
    [string]$CMake = "cmake"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$installPath = [IO.Path]::GetFullPath($InstallRoot)
$buildPath = [IO.Path]::GetFullPath($BuildRoot)
$sdkPath = [IO.Path]::GetFullPath($SdkRoot)
$sourcePath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../agent"))
& $CMake -S $sourcePath -B $buildPath "-DMAA_SDK=$sdkPath" -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE -ne 0) { throw "Native Agent configuration failed" }
& $CMake --build $buildPath --config Release --parallel
if ($LASTEXITCODE -ne 0) { throw "Native Agent build failed" }
$testExe = Join-Path $buildPath "Release/MaaRocoAgentTests.exe"
if (-not (Test-Path -LiteralPath $testExe)) { $testExe = Join-Path $buildPath "MaaRocoAgentTests.exe" }
& $testExe
if ($LASTEXITCODE -ne 0) { throw "Native Agent strategy tests failed" }
& $CMake --install $buildPath --config Release --prefix $installPath
if ($LASTEXITCODE -ne 0) { throw "Native Agent installation failed" }
foreach ($name in @("MaaRocoAgent", "MaaRocoRunner")) {
    & (Join-Path $installPath "runtimes/win-x64/native/$name.exe") --check
    if ($LASTEXITCODE -ne 0) { throw "$name failed to load packaged framework libraries" }
}
