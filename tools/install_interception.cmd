@echo off
setlocal EnableExtensions

set "VERSION=latest"
set "RELEASE_URL=https://github.com/oblitum/Interception/releases/latest/download/Interception.zip"
set "WORK_DIR=%TEMP%\MaaRoco-Interception-%VERSION%"
set "ZIP_FILE=%WORK_DIR%\Interception.zip"
set "EXTRACT_DIR=%WORK_DIR%\extracted"

if /I not "%OS%"=="Windows_NT" (
    echo This script can only run on Windows.
    pause
    exit /b 1
)

rem The Interception installer requires an elevated command prompt.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 0 }; exit 1"
if errorlevel 1 (
    echo Requesting administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    if errorlevel 1 (
        echo Failed to request administrator permission.
        pause
    )
    exit /b
)

echo Administrator permissions verified.

echo Downloading Interception %VERSION% from the official GitHub release...
if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
mkdir "%EXTRACT_DIR%" >nul 2>&1
if errorlevel 1 goto :error_create_directory

powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri '%RELEASE_URL%' -OutFile '%ZIP_FILE%'"
if errorlevel 1 goto :error_download

echo Extracting the installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force"
if errorlevel 1 goto :error_extract

set "INSTALLER_DIR=%EXTRACT_DIR%\Interception\command line installer"
set "INSTALLER=%INSTALLER_DIR%\install-interception.exe"
if not exist "%INSTALLER%" (
    echo Could not find the official command-line installer in the downloaded archive.
    goto :error_keep_files
)

echo Installing the Interception driver...
echo Using installer: "%INSTALLER%"
pushd "%INSTALLER_DIR%"
if errorlevel 1 goto :error_install
install-interception.exe /install
set "INSTALL_EXIT=%ERRORLEVEL%"
popd
if not "%INSTALL_EXIT%"=="0" goto :error_install

echo.
echo Interception %VERSION% was installed successfully.
echo Restart Windows before using the driver.
rmdir /s /q "%WORK_DIR%"
pause
exit /b 0

:error_create_directory
echo Failed to create the temporary download directory.
goto :error

:error_download
echo Download failed. Check your network connection and try again.
goto :error_keep_files

:error_extract
echo Extraction failed. The downloaded archive may be incomplete.
goto :error_keep_files

:error_install
echo Driver installation failed. The installer files were kept for inspection.
echo.
echo Removing any incomplete or previous Interception driver installation...
if not exist "%INSTALLER%" goto :error_keep_files
pushd "%INSTALLER_DIR%"
if errorlevel 1 goto :error_keep_files
install-interception.exe /uninstall
set "CLEANUP_EXIT=%ERRORLEVEL%"
popd
if not "%CLEANUP_EXIT%"=="0" (
    echo Automatic cleanup did not complete. Do not delete driver files manually.
    goto :error_keep_files
)
echo Cleanup completed.
echo Restart Windows, then double-click this script again to install the driver.
goto :error_keep_files

:error_keep_files
echo Temporary files: "%WORK_DIR%"

:error
pause
exit /b 1
