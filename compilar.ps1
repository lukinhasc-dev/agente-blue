# compilar.ps1 — Agente Blue
#
# Uso:
#   .\compilar.ps1               # build ONEDIR (dev/testes) -> dist\AgenteBlue\AgenteBlue.exe + _internal\
#   .\compilar.ps1 -AssetsOnly   # so atualiza HTML/JS/CSS/apps no onedir (NAO recompila)
#   .\compilar.ps1 -Onefile      # build ONEFILE (entrega)   -> dist\AgenteBlue.exe (arquivo unico)
#
# Sempre sobrescreve o mesmo destino. Nunca gera _old_, dist_new nem copias com timestamp.

param(
    [switch]$AssetsOnly,
    [switch]$Onefile
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$AppName    = 'AgenteBlue'
$DistDir    = Join-Path $PSScriptRoot 'dist'
$OutDir     = Join-Path $DistDir $AppName            # saida onedir (pasta)
$ExePath    = Join-Path $OutDir "$AppName.exe"
$OnefileExe = Join-Path $DistDir "$AppName.exe"      # saida onefile (arquivo unico)
$Assets     = @('index.html', 'script.js', 'style.css', 'bluepay-ico.ico', 'config.json')

if ($AssetsOnly -and $Onefile) {
    Write-Host " [ERRO] -AssetsOnly nao se aplica ao onefile (assets ficam embutidos no exe)." -ForegroundColor Red
    exit 1
}

$modo = if ($Onefile) { 'ONEFILE (entrega)' } else { 'ONEDIR (dev)' }

function Write-Step($n, $msg) { Write-Host " [$n] $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host " ===================================================" -ForegroundColor Cyan
Write-Host "   AGENTE BLUE  |  COMPILADOR  -  $modo" -ForegroundColor Cyan
Write-Host " ===================================================" -ForegroundColor Cyan
Write-Host ""

# ── Encerrar instâncias em execução (libera arquivos travados) ──────────
Write-Step '1/4' 'Encerrando instancias do Agente...'
$names = @('AgenteBlue', 'AgenteBlue_PRO', 'AgenteBlue2', 'AgenteBlue_old')
foreach ($n in $names) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 800

function Copy-Assets {
    if (-not (Test-Path $OutDir)) {
        throw "Pasta de saida nao existe ($OutDir). Rode o build completo primeiro (sem -AssetsOnly)."
    }
    foreach ($f in $Assets) {
        if (Test-Path $f) { Copy-Item $f -Destination $OutDir -Force }
    }
    Get-ChildItem -Path $PSScriptRoot -Filter 'Fundo de Tela.*' -File -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item $_.FullName -Destination $OutDir -Force }
    $appsSrc = Join-Path $PSScriptRoot 'apps'
    if (Test-Path $appsSrc) {
        Copy-Item $appsSrc -Destination $OutDir -Recurse -Force
    }
    Write-Host "  [OK] Assets atualizados em $OutDir" -ForegroundColor Green
}

# ── Modo rápido: só atualiza os arquivos, sem recompilar ────────────────
if ($AssetsOnly) {
    Write-Host " Modo -AssetsOnly: atualizando arquivos sem recompilar..." -ForegroundColor Cyan
    Copy-Assets
    Write-Host ""
    Write-Host " Pronto. Execute: $ExePath" -ForegroundColor Green
    exit 0
}

# ── Build PyInstaller em pasta temporária ───────────────────────────────
Write-Step '2/4' "Compilando ($modo)..."
$work    = Join-Path $env:TEMP 'agenteblue_build'
$tmpDist = Join-Path $env:TEMP 'agenteblue_dist'
Remove-Item -Recurse -Force $work, $tmpDist -ErrorAction SilentlyContinue

if ($Onefile) { $env:AGENTEBLUE_ONEFILE = '1' } else { Remove-Item Env:\AGENTEBLUE_ONEFILE -ErrorAction SilentlyContinue }
& python -m PyInstaller --noconfirm --clean --distpath $tmpDist --workpath $work 'AgenteBlue.spec'
$buildOk = ($LASTEXITCODE -eq 0)
Remove-Item Env:\AGENTEBLUE_ONEFILE -ErrorAction SilentlyContinue
if (-not $buildOk) {
    Write-Host " [ERRO] Falha na compilacao do PyInstaller!" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $DistDir)) { New-Item -ItemType Directory -Path $DistDir | Out-Null }

if ($Onefile) {
    # ── ONEFILE: publica um unico .exe em dist\AgenteBlue.exe ────────────
    $builtExe = Join-Path $tmpDist "$AppName.exe"
    if (-not (Test-Path $builtExe)) {
        Write-Host " [ERRO] Executavel nao encontrado em $builtExe!" -ForegroundColor Red
        exit 1
    }
    Write-Step '3/4' "Publicando arquivo unico em $OnefileExe..."
    try {
        Copy-Item $builtExe -Destination $OnefileExe -Force -ErrorAction Stop
    } catch {
        Write-Host " [ERRO] Nao foi possivel substituir $OnefileExe (feche o Agente Blue)." -ForegroundColor Red
        exit 1
    }
    $resultExe = $OnefileExe
} else {
    # ── ONEDIR: publica a pasta unica dist\AgenteBlue\ ───────────────────
    $built = Join-Path $tmpDist $AppName
    if (-not (Test-Path (Join-Path $built "$AppName.exe"))) {
        Write-Host " [ERRO] Executavel nao encontrado em $built!" -ForegroundColor Red
        exit 1
    }
    Write-Step '3/4' "Publicando pasta em $OutDir..."
    if (Test-Path $OutDir) {
        try {
            Remove-Item -Recurse -Force $OutDir -ErrorAction Stop
        } catch {
            Write-Host " [ERRO] Nao foi possivel substituir $OutDir." -ForegroundColor Red
            Write-Host "        Feche o Agente Blue (e o Explorer aberto na pasta) e rode de novo." -ForegroundColor Red
            exit 1
        }
    }
    Move-Item -Path $built -Destination $OutDir -Force
    Write-Step '4/4' 'Copiando assets externos...'
    Copy-Assets
    $resultExe = $ExePath
}

# ── Limpeza dos temporários ─────────────────────────────────────────────
Remove-Item -Recurse -Force $work, $tmpDist -ErrorAction SilentlyContinue

# ── Resultado ───────────────────────────────────────────────────────────
$exe = Get-Item $resultExe
$mb  = [math]::Round($exe.Length / 1MB, 1)
Write-Host ""
Write-Host " ===================================================" -ForegroundColor Green
Write-Host "   BUILD CONCLUIDO  -  $modo" -ForegroundColor Green
Write-Host "   Exe:  $($exe.FullName)" -ForegroundColor Green
Write-Host "   Tam:  $mb MB    Data: $($exe.LastWriteTime)" -ForegroundColor Green
Write-Host " ===================================================" -ForegroundColor Green
Write-Host ""
if ($Onefile) {
    Write-Host " Entrega: copie este .exe + a pasta apps\ + Fundo de Tela.jpg para o pendrive." -ForegroundColor DarkGray
} else {
    Write-Host " Dica: alterou so a interface (html/js/css)? Use:" -ForegroundColor DarkGray
    Write-Host "   .\compilar.ps1 -AssetsOnly   (atualiza sem recompilar)" -ForegroundColor DarkGray
}
Write-Host ""
