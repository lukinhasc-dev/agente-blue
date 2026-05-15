# compilar.ps1 — Agente Blue
# Execução: powershell -ExecutionPolicy Bypass -File .\compilar.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host ""
Write-Host " ===================================================" -ForegroundColor Cyan
Write-Host "   AGENTE BLUE  |  COMPILADOR" -ForegroundColor Cyan
Write-Host " ===================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Encerrar processos ──────────────────────────────
Write-Host " [1/4] Encerrando processos..." -ForegroundColor Yellow
$processNames = @('AgenteBlue_PRO', 'AgenteBlue', 'AgenteBlue2', 'AgenteBlue_old')
foreach ($name in $processNames) {
    try {
        Stop-Process -Name $name -Force -ErrorAction SilentlyContinue
    } catch {}
}
# Taskkill como fallback extra - ignorando erros
& cmd /c "taskkill /F /IM AgenteBlue_PRO.exe /T 2>nul" | Out-Null
& cmd /c "taskkill /F /IM AgenteBlue.exe /T 2>nul" | Out-Null
Start-Sleep -Seconds 2

# ── 2. Limpar pastas de build ─────────────────────────────────
Write-Host " [2/4] Limpando builds anteriores..." -ForegroundColor Yellow
$folders = @('dist_new', 'build')
foreach ($folder in $folders) {
    if (Test-Path $folder) {
        Remove-Item -Recurse -Force $folder -ErrorAction SilentlyContinue
    }
}

# ── 3. Compilar ────────────────────────────────────────────────────────────
Write-Host " [3/4] Compilando..." -ForegroundColor Yellow
Write-Host ""

# Executa PyInstaller
$pyArgs = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', 'dist_new', '--workpath', 'build', 'AgenteBlue.spec')
& python $pyArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host " [ERRO] Falha na compilação do PyInstaller!" -ForegroundColor Red
    # Read-Host removido para automação
    exit 1
}

$novoExe = Join-Path "dist_new" "AgenteBlue_PRO.exe"
if (-not (Test-Path $novoExe)) {
    Write-Host " [ERRO] Novo executável não foi encontrado em dist_new!" -ForegroundColor Red
    # Read-Host removido para automação
    exit 1
}

# ── 4. Publicar ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host " [4/4] Publicando..." -ForegroundColor Yellow

if (-not (Test-Path "dist")) {
    New-Item -ItemType Directory "dist" | Out-Null
}

$destExe = Join-Path "dist" "AgenteBlue_PRO.exe"

# Tenta remover ou renomear o arquivo antigo para liberar o caminho
if (Test-Path $destExe) {
    try {
        Remove-Item -Path $destExe -Force -ErrorAction Stop
    } catch {
        Write-Host "  [AVISO] Arquivo de destino está bloqueado. Tentando renomear..." -ForegroundColor DarkYellow
        $oldFile = Join-Path "dist" ("AgenteBlue_PRO_old_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".exe")
        try {
            Rename-Item -Path $destExe -NewName (Split-Path $oldFile -Leaf) -Force -ErrorAction Stop
            Write-Host "  [OK] Arquivo antigo renomeado para liberar o caminho." -ForegroundColor Gray
        } catch {
            Write-Host " [ERRO] O executável antigo está sendo usado e não pôde ser movido ou excluído." -ForegroundColor Red
            Write-Host " Por favor, feche o Agente Blue e tente novamente." -ForegroundColor Red
            # Read-Host removido para automação
            exit 1
        }
    }
}

# Copia o novo executável
try {
    Copy-Item -Path $novoExe -Destination $destExe -Force -ErrorAction Stop
    Write-Host "  [OK] Executável atualizado com sucesso em dist\" -ForegroundColor Gray
    
    # Sincroniza com a pasta AGENTE_FINAL para o pendrive
    $finalFolder = Join-Path $PSScriptRoot "AGENTE_FINAL"
    if (-not (Test-Path $finalFolder)) { New-Item -ItemType Directory -Path $finalFolder | Out-Null }
    Copy-Item -Path $destExe -Destination (Join-Path $finalFolder "AgenteBlue_PRO.exe") -Force
    Write-Host "  [OK] Cópia atualizada em AGENTE_FINAL\ para Pendrive." -ForegroundColor Cyan
} catch {
    Write-Host " [ERRO] Falha ao copiar o novo executável para dist\" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    # Read-Host removido para automação
    exit 1
}

# Limpeza final
Remove-Item -Recurse -Force 'dist_new', 'build' -ErrorAction SilentlyContinue

# ── Resultado ──────────────────────────────────────────────────────────────
Write-Host ""
$file = Get-Item $destExe
$mb = [math]::Round($file.Length / 1MB, 1)
Write-Host " ===================================================" -ForegroundColor Green
Write-Host "   SUCESSO! AGENTE ATUALIZADO" -ForegroundColor Green
Write-Host "   Arquivo: $($file.FullName)" -ForegroundColor Green
Write-Host "   Tamanho: $mb MB" -ForegroundColor Green
Write-Host "   Data/Hora: $($file.LastWriteTime)" -ForegroundColor Green
Write-Host " ===================================================" -ForegroundColor Green
Write-Host ""
# Read-Host removido para automação
