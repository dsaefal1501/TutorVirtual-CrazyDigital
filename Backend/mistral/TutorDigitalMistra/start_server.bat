@echo off
cd /d "%~dp0"
echo Iniciando el servidor uvicorn (Tutor Digital)...

:: Intentar usar el entorno virtual si funciona, sino usar Python del sistema
if exist env\Scripts\python.exe (
    env\Scripts\python.exe run.py
) else (
    echo Entorno virtual no encontrado, usando Python del sistema...
    python run.py
)
pause