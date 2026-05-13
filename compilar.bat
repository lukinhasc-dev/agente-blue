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

:: ─── PASSO 1: Encerrar processos ────────────────────────────────────────
echo  [1/4] Encerrando processos em execucao...
taskkill /F /IM AgenteBlue.exe /T >nul 2>&1
taskkill /F /IM AgenteBlue2.exe /T >nul 2>&1
taskkill /F /IM AgenteBlue_old.exe /T >nul 2>&1
ping 127.0.0.1 -n 4 >nul

:: ─── PASSO 2: Limpar pastas de build antigas ─────────────────────────────
echo  [2/4] Limpando builds anteriores...
if exist "dist_new\"  rmdir /S /Q "dist_new"  >nul 2>&1
if exist "build\"     rmdir /S /Q "build"     >nul 2>&1

:: ─── PASSO 3: Compilar direto em dist_new ──────────────────────────────
echo  [3/4] Compilando...
echo.

python -m PyInstaller --noconfirm --distpath "dist_new" --workpath "build" AgenteBlue.spec

if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha na compilacao. Verifique o log acima.
    pause & exit /b 1
)

if not exist "dist_new\AgenteBlue.exe" (
    echo  [ERRO] PyInstaller nao gerou o executavel esperado.
    pause & exit /b 1
)

:: ─── PASSO 4: Publicar — substituir dist\ pelo novo ────────────────────
echo.
echo  [4/4] Publicando novo executavel...

:: Apaga o exe antigo (force, mesmo que seja read-only)
if exist "dist\AgenteBlue.exe" (
    attrib -R "dist\AgenteBlue.exe" >nul 2>&1
    del /F /Q "dist\AgenteBlue.exe" >nul 2>&1
)

:: Garante que dist\ existe
if not exist "dist\" mkdir "dist"

:: Copia o novo exe
xcopy /Y "dist_new\AgenteBlue.exe" "dist\" >nul 2>&1

:: Remove pasta temporaria de compilacao
rmdir /S /Q "dist_new" >nul 2>&1
rmdir /S /Q "build"    >nul 2>&1

:: ─── Resultado ───────────────────────────────────────────────────────────
echo.
if exist "dist\AgenteBlue.exe" (
    for %%F in ("dist\AgenteBlue.exe") do set /a MB=%%~zF / 1048576
    echo  ===================================================
    echo    SUCESSO!
    echo    Executavel: %CD%\dist\AgenteBlue.exe
    echo    Tamanho:    ~!MB! MB
    echo  ===================================================
) else (
    echo  [ERRO] Executavel nao encontrado em dist\
    echo  Verifique os logs acima.
)
echo.
pause
endlocal
