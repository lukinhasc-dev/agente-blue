@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Agente Blue — Compilador

echo.
echo  ===================================================
echo    AGENTE BLUE  ^|  COMPILADOR AUTOMATICO
echo  ===================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERRO] Python nao encontrado no PATH.
    pause & exit /b 1
)

:: ─── PASSO 1: Encerrar processos que podem bloquear arquivos ─────────────────
echo  [1/4] Encerrando processos em execucao...
taskkill /F /IM AgenteBlue_PRO.exe  /T >nul 2>&1
taskkill /F /IM AgenteBlue.exe      /T >nul 2>&1
taskkill /F /IM AgenteBlue2.exe     /T >nul 2>&1
taskkill /F /IM AgenteBlue_old.exe  /T >nul 2>&1
ping 127.0.0.1 -n 3 >nul

:: ─── PASSO 2: Limpar pastas antigas ──────────────────────────────────────────
echo  [2/4] Limpando builds anteriores...

:: Remove via script PS auxiliar (resolve bloqueios de permissao)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0limpar.ps1" -Path "%~dp0dist_new"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0limpar.ps1" -Path "%~dp0build"

:: Fallback cmd
if exist "dist_new\" ( attrib -R -S -H "dist_new\*" /S /D >nul 2>&1 & rmdir /S /Q "dist_new" >nul 2>&1 )
if exist "build\"    ( attrib -R -S -H "build\*"    /S /D >nul 2>&1 & rmdir /S /Q "build"    >nul 2>&1 )

:: Se dist_new ainda existe, o exe esta bloqueado (antivirus/processo ativo)
if exist "dist_new\AgenteBlue_PRO.exe" (
    echo  [AVISO] dist_new\AgenteBlue_PRO.exe esta bloqueado.
    echo          Tentando renomear para compilar mesmo assim...
    rename "dist_new\AgenteBlue_PRO.exe" "AgenteBlue_PRO.old" >nul 2>&1
    if exist "dist_new\AgenteBlue_PRO.exe" (
        echo  [ERRO] Impossivel liberar o arquivo. Feche o executavel e tente novamente.
        pause & exit /b 1
    )
)

:: ─── PASSO 3: Compilar ────────────────────────────────────────────────────────
echo  [3/4] Compilando...
echo.

python -m PyInstaller --noconfirm --distpath "dist_new" --workpath "build" AgenteBlue.spec

if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha na compilacao. Verifique o log acima.
    pause & exit /b 1
)

if not exist "dist_new\AgenteBlue_PRO.exe" (
    echo  [ERRO] PyInstaller nao gerou dist_new\AgenteBlue_PRO.exe
    pause & exit /b 1
)

:: ─── PASSO 4: Publicar ───────────────────────────────────────────────────────
echo.
echo  [4/4] Publicando novo executavel...

if not exist "dist\" mkdir "dist"

:: Remover exe antigo
if exist "dist\AgenteBlue_PRO.exe" (
    attrib -R "dist\AgenteBlue_PRO.exe" >nul 2>&1
    del /F /Q "dist\AgenteBlue_PRO.exe" >nul 2>&1
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0limpar.ps1" -Path "%~dp0dist\AgenteBlue_PRO.exe"
)

:: Copia o novo
xcopy /Y "dist_new\AgenteBlue_PRO.exe" "dist\" >nul 2>&1

:: Limpa temporarios
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0limpar.ps1" -Path "%~dp0dist_new"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0limpar.ps1" -Path "%~dp0build"
if exist "dist_new\" rmdir /S /Q "dist_new" >nul 2>&1
if exist "build\"    rmdir /S /Q "build"    >nul 2>&1

:: ─── Resultado ────────────────────────────────────────────────────────────────
echo.
if exist "dist\AgenteBlue_PRO.exe" (
    for %%F in ("dist\AgenteBlue_PRO.exe") do set /a MB=%%~zF / 1048576
    echo  ===================================================
    echo    SUCESSO!
    echo    Executavel: %CD%\dist\AgenteBlue_PRO.exe
    echo    Tamanho:    ~!MB! MB
    echo  ===================================================
) else (
    echo  [ERRO] Executavel nao encontrado em dist\
)
echo.
pause
endlocal
