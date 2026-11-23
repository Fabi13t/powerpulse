@echo off
title PowerPulse - Panel de control
cd /d "%~dp0"
echo ==========================================
echo        PowerPulse - Iniciando sistema
echo ==========================================

rem --- 1. Compila el recolector solo si aun no existe el .exe ---
if not exist "recolector.exe" (
    echo [1/4] Compilando el recolector C++...
    g++ recolector.cpp -o recolector.exe -lws2_32 -lsetupapi
    if errorlevel 1 (
        echo ERROR: no se pudo compilar el recolector.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Recolector ya compilado.
)

rem --- 2. Inicia el gestor Python primero (debe estar escuchando) ---
echo [2/4] Iniciando el gestor Python...
start "PowerPulse - Gestor (Python)" cmd /k python gestor.py
timeout /t 2 /nobreak >nul

rem --- 3. Inicia el recolector C++ ---
echo [3/4] Iniciando el recolector C++...
start "PowerPulse - Recolector (C++)" cmd /k recolector.exe

rem --- 4. Inicia el dashboard web (Flask) y abre el navegador ---
echo [4/4] Iniciando el dashboard web...
start "PowerPulse - Dashboard (Flask)" cmd /k python dashboard\app.py
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:5000

echo.
echo ==========================================
echo   PowerPulse esta en ejecucion.
echo   Dashboard: http://127.0.0.1:5000
echo   Presiona cualquier tecla AQUI para DETENERLO.
echo ==========================================
pause >nul

rem --- 5. Detiene los tres componentes ---
echo Deteniendo PowerPulse...
taskkill /fi "WINDOWTITLE eq PowerPulse - Recolector*" /t /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq PowerPulse - Gestor*" /t /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq PowerPulse - Dashboard*" /t /f >nul 2>&1
rem En Windows Terminal el titulo no siempre coincide: se detiene tambien por proceso
taskkill /im recolector.exe /f >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and ($_.CommandLine -like '*gestor.py*' -or $_.CommandLine -like '*dashboard*app.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo Listo: recolector, gestor y dashboard detenidos.
timeout /t 3 >nul
