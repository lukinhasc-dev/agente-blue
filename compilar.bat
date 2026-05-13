@echo off
:: Garante que o script rode na pasta onde ele esta localizado
cd /d "%~dp0"

echo ==================================================
echo   COMPILANDO AGENTE BLUE - Gerando Executavel
echo ==================================================
echo.

:: Verifica se o Python esta no PATH
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado no PATH.
    pause
    exit /b
)

echo [1/3] Tentando fechar processos antigos do Agente Blue...
taskkill /F /IM AgenteBlue.exe /T >nul 2>&1
echo Aguardando 2 segundos...
ping 127.0.0.1 -n 3 >nul

echo [2/3] Iniciando o PyInstaller...
echo ATENCAO: Se der erro de 'Acesso Negado', feche o Agente Blue manualmente!
python -m PyInstaller --noconfirm AgenteBlue.spec

if %errorlevel% equ 0 (
    echo.
    echo ==================================================
    echo   SUCESSO! O executavel foi gerado em:
    echo   %CD%\dist\AgenteBlue.exe
    echo ==================================================
) else (
    echo.
    echo [ERRO] Houve um problema na compilacao.
    echo --------------------------------------------------
    echo DICA: Se o erro for 'Acesso Negado', tente:
    echo 1. Fechar o Agente Blue manualmente no Gerenciador de Tarefas.
    echo 2. Clicar com o botao direito neste arquivo e escolher 
    echo    'Executar como administrador'.
    echo --------------------------------------------------
)

pause
