@echo off
echo Activando entorno virtual...
if exist env\Scripts\activate.bat (
    call env\Scripts\activate.bat
) else (
    echo No se encontró el entorno virtual en env\Scripts\activate.bat. Continuando sin activar...
)

echo Iniciando el servidor uvicorn (Tutor Digital)...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause
