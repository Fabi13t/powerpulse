# PowerPulse

Monitor de energía, batería y control ACPI para laptops Windows.

## Requisitos
- Windows 10/11
- MinGW (g++)
- Python 3 y `pip install plyer`

## Arquitectura
- **Recolector (C++)**: consulta `GetSystemPowerStatus()`, `GetSystemTimes()` y el driver ACPI de la batería (`DeviceIoControl`) cada 2 s, y envía la telemetría en JSON por UDP a `127.0.0.1:5005`.
- **Gestor (Python)**: valida los datos, calcula la salud de la batería y la tasa de descarga, emite alertas con Plyer, activa el plan de ahorro de Windows (`powercfg`) bajo el 20 % y guarda un CSV diario adaptativo en `%LOCALAPPDATA%\PowerPulse\logs\` (retención de 30 días).

## Ejecución
```
g++ recolector/recolector.cpp -o recolector.exe -lws2_32 -lsetupapi
python gestor/gestor.py
recolector.exe
```

## Autora
Fabiana Alicia Quispe Tacza – Universidad Tecnológica del Perú
