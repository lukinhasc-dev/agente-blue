@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Agente Blue — Compilador

echo ==================================================
echo   AGENTE BLUE — COMPILADOR AUTOMATICO
echo ==================================================
echo.

:: ── 1. Verificar Python ───────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado no PATH.
    pause & exit /b 1
)

:: ── 2. Matar todos os processos do Agente Blue ───────────────────────────
echo [1/5] Encerrando processos antigos...
for %%P in (AgenteBlue.exe AgenteBlue2.exe AgenteBlue_NOVO.exe AgenteBlue_novo.exe AgenteBlue_old.exe) do (
    taskkill /F /IM "%%P" /T >nul 2>&1
)
ping 127.0.0.1 -n 4 >nul

:: ── 3. Renomear exe antigo (funciona mesmo se ainda em uso pelo Windows) ──
echo [2/5] Preparando pasta de saida...
if exist "dist\AgenteBlue.exe" (
    ren "dist\AgenteBlue.exe" "AgenteBlue_old.exe" >nul 2>&1
    if exist "dist\AgenteBlue_old.exe" (
        echo    Antigo renomeado para AgenteBlue_old.exe
        :: Tenta deletar o renomeado imediatamente
        del /F /Q "dist\AgenteBlue_old.exe" >nul 2>&1
    )
)
:: Limpa outros residuos
for %%F in (dist\AgenteBlue2.exe dist\AgenteBlue_NOVO.exe dist_new\AgenteBlue.exe) do (
    if exist "%%F" del /F /Q "%%F" >nul 2>&1
)
if exist "dist_new\" rmdir /S /Q "dist_new" >nul 2>&1
echo    Pronto.
echo.

:: ── 4. Compilar direto em dist\ ──────────────────────────────────────────
echo [3/5] Compilando com PyInstaller...
echo.
python -m PyInstaller --noconfirm --distpath "dist" AgenteBlue.spec

if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Falha na compilacao.
    echo.
    echo Solucao: Execute este .bat como Administrador.
    pause & exit /b 1
)

:: ── 5. Limpar o _old se ainda existir ────────────────────────────────────
if exist "dist\AgenteBlue_old.exe" del /F /Q "dist\AgenteBlue_old.exe" >nul 2>&1
echo [4/5] Residuos removidos.

:: ── 6. Resultado ──────────────────────────────────────────────────────────
echo.
set "FINAL=dist\AgenteBlue.exe"
if exist "!FINAL!" (
    for %%F in ("!FINAL!") do set /a MB=%%~zF / 1048576
    echo [5/5] Executavel gerado com sucesso!
    echo.
    echo ==================================================
    echo   SUCESSO!
    echo   Arquivo: %CD%\dist\AgenteBlue.exe
    echo   Tamanho: ~!MB! MB
    echo ==================================================
) else (
    echo [AVISO] Executavel nao encontrado. Verifique os logs acima.
)
echo.
pause
endlocal
