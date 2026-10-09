@echo off
REM Lanzador del ciclo para el Programador de tareas de Windows.
REM
REM Existe por dos motivos que el Programador no resuelve solo:
REM   1. La salida de una tarea programada se pierde. Aqui se acumula en
REM      logs\ciclo.log, que es lo unico que te dira manana por que no llego
REM      ninguna alerta.
REM   2. El Programador no fija el directorio de trabajo, y runner.py resuelve
REM      config/, data/ y logs/ relativos a el. Sin el `cd` corre en C:\Windows
REM      y no encuentra nada.

cd /d "%~dp0.."
if not exist logs mkdir logs

echo. >> logs\ciclo.log
echo ===== %DATE% %TIME% ===== >> logs\ciclo.log
python runner.py >> logs\ciclo.log 2>&1
echo ----- fin, codigo %ERRORLEVEL% ----- >> logs\ciclo.log
