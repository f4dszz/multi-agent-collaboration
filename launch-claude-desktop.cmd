@echo off
setlocal

set "APPID=Claude_pzs8sxrjxfjjc!Claude"
set "EXE=C:\Program Files\WindowsApps\Claude_1.2.234.0_x64__pzs8sxrjxfjjc\app\Claude.exe"
set "SVC=C:\Program Files\WindowsApps\Claude_1.2.234.0_x64__pzs8sxrjxfjjc\app\resources\cowork-svc.exe"

echo Launching Claude Desktop...
echo AppUserModelID: %APPID%
echo Claude.exe: %EXE%
echo cowork-svc.exe: %SVC%

start "" explorer.exe "shell:AppsFolder\%APPID%"

endlocal
