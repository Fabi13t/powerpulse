# PowerPulse

Monitor de energía, batería y control ACPI para laptops Windows.

## Arquitectura
- **Recolector (C++)**: consulta `GetSystemPowerStatus()` y `GetSystemTimes()` cada 2 s y envía la telemetría en JSON por UDP a `127.0.0.1:5005`.
- **Gestor (Python)**: recibe los datos, evalúa el umbral de batería (< 20 %), emite notificaciones con Plyer y guarda un CSV diario en `%LOCALAPPDATA%\PowerPulse\logs\` (retención de 30 días).

## Requisitos
- Windows 10/11
- MinGW (g++)
- Python 3 y `pip install plyer`

## Ejecución
```
g++ recolector/recolector.cpp -o recolector.exe -lws2_32
recolector.exe
python gestor/gestor.py
```

## Autora
Fabiana Alicia Quispe Tacza – Universidad Tecnológica del Perú
