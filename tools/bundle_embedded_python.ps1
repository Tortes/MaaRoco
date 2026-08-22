param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,

    [string]$Requirements = (Join-Path $PSScriptRoot "runtime-requirements.txt"),
    [string]$HostPython = "python",
    [string]$PythonVersion = "3.12.10",
    [string]$ExpectedSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installPath = [System.IO.Path]::GetFullPath($InstallRoot)
$requirementsPath = [System.IO.Path]::GetFullPath($Requirements)
$pythonPath = Join-Path $installPath "python"

if (-not (Test-Path -LiteralPath $installPath -PathType Container)) {
    throw "Install directory does not exist: $installPath"
}
if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw "Runtime requirements file does not exist: $requirementsPath"
}
if (Test-Path -LiteralPath $pythonPath) {
    throw "Embedded Python destination already exists: $pythonPath"
}

$versionParts = $PythonVersion.Split(".")
if ($versionParts.Length -lt 2) {
    throw "Invalid Python version: $PythonVersion"
}
$majorMinor = "$($versionParts[0]).$($versionParts[1])"
$abiTag = "cp$($versionParts[0])$($versionParts[1])"
$pthName = "python$($versionParts[0])$($versionParts[1])._pth"
$archiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$archivePath = Join-Path ([System.IO.Path]::GetTempPath()) "maaroco-python-$PythonVersion-$([guid]::NewGuid().ToString('N')).zip"

try {
    Write-Host "Downloading CPython $PythonVersion embeddable package..."
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath

    $actualSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "CPython archive SHA-256 mismatch: expected $ExpectedSha256, got $actualSha256"
    }

    New-Item -ItemType Directory -Path $pythonPath | Out-Null
    Expand-Archive -LiteralPath $archivePath -DestinationPath $pythonPath

    $pthPath = Join-Path $pythonPath $pthName
    if (-not (Test-Path -LiteralPath $pthPath -PathType Leaf)) {
        throw "Embedded Python path configuration is missing: $pthPath"
    }

    $pthLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in [System.IO.File]::ReadAllLines($pthPath)) {
        if ($line.Trim() -eq "#import site") {
            $pthLines.Add("import site")
        }
        else {
            $pthLines.Add($line)
        }
    }
    if (-not $pthLines.Contains("Lib\site-packages")) {
        $pthLines.Insert([Math]::Max(0, $pthLines.Count - 1), "Lib\site-packages")
    }
    if (-not $pthLines.Contains("import site")) {
        $pthLines.Add("import site")
    }
    [System.IO.File]::WriteAllLines(
        $pthPath,
        $pthLines,
        [System.Text.UTF8Encoding]::new($false)
    )

    $sitePackages = Join-Path $pythonPath "Lib\site-packages"
    New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null

    Write-Host "Installing pinned MaaRoco runtime dependencies..."
    & $HostPython -m pip install `
        --disable-pip-version-check `
        --no-cache-dir `
        --only-binary=:all: `
        --platform win_amd64 `
        --python-version $majorMinor `
        --implementation cp `
        --abi $abiTag `
        --target $sitePackages `
        --requirement $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Installing embedded Python dependencies failed with exit code $LASTEXITCODE"
    }

    $embeddedPython = Join-Path $pythonPath "python.exe"
    $smokeTest = @"
import cv2
import interception
import maa
import numpy
from maa.agent.agent_server import AgentServer

print(f"MaaFw={maa.__version__ if hasattr(maa, '__version__') else 'loaded'}")
print(f"OpenCV={cv2.__version__}")
print(f"NumPy={numpy.__version__}")
print("MaaRoco embedded Python smoke test passed")
"@
    & $embeddedPython -I -c $smokeTest
    if ($LASTEXITCODE -ne 0) {
        throw "Embedded Python smoke test failed with exit code $LASTEXITCODE"
    }

    $agentPath = Join-Path $installPath "agent"
    if (Test-Path -LiteralPath $agentPath -PathType Container) {
        & $embeddedPython -m compileall -q $agentPath
        if ($LASTEXITCODE -ne 0) {
            throw "Agent syntax check failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        Remove-Item -LiteralPath $archivePath -Force
    }
}
