"""
agente.py — Agente Blue
=======================
Automação Windows sem dependências externas.

Arquitetura:
  - Servidor HTTP local (stdlib) serve a interface HTML
  - Server-Sent Events (SSE) enviam logs em tempo real ao browser
  - Edge/Chrome abre em modo --app (janela limpa, sem abas)

Ordem de execução ao clicar em Executar:
  1. Downloads e instalações de software (com progresso individual)
  2. Papel de parede
  3. Configuração de Descoberta de Rede (firewall + serviços)
  4. Configuração SMB (desativar assinatura)
"""

import ctypes
import http.server
import json
import logging
import os
import queue
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

# ─────────────────────────────────────────────
#  CREDENCIAIS DE ADMINISTRADOR
# ─────────────────────────────────────────────
_ADMIN_USER: str = r".\Administrator"
_ADMIN_PASS: str = "Sham23*"

_NET_USER: str = "scanner"
_NET_PASS: str = "teste123"

# ─────────────────────────────────────────────
#  CAMINHOS
# ─────────────────────────────────────────────
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _BASE_DIR = Path(sys._MEIPASS)
else:
    _BASE_DIR = Path(__file__).resolve().parent

_LOG_FILE = Path(os.environ.get("TEMP", "C:\\Temp")) / "agente_blue.log"

# Wallpaper: procura o arquivo "Fundo de Tela.*" na raiz do executável / script
_WALLPAPER_NAMES = [
    "Fundo de Tela.jpg", "Fundo de Tela.jpeg",
    "Fundo de Tela.png", "Fundo de Tela.bmp",
]

# ─────────────────────────────────────────────
#  LOG
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("agente-blue")

# ─────────────────────────────────────────────
# (nome, url, filename, silent_args, ok_codes)
# Se url == "" → instala via winget (args = comando winget completo)
# ok_codes: set de códigos de saída considerados sucesso (padrão {0})
# ─────────────────────────────────────────────
# (Nome, Arquivo em 'apps/', Argumentos, Códigos de OK, Caminho de Detecção)
SOFTWARES: List[Tuple] = [
    (
        "AnyDesk",
        "AnyDesk.exe",
        '--install "C:\\Program Files (x86)\\AnyDesk" --silent --start-with-win --create-shortcuts --create-desktop-icon',
        {0, 11},
        r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe"
    ),
    (
        "Google Chrome",
        "ChromeSetup.exe",
        "/silent /install",
        {0, 1603, 3010},
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    ),
    (
        "Google Drive",
        "GoogleDriveSetup.exe",
        "--silent --desktop_shortcut --skip_launch_new --gsuite_shortcuts=false",
        {0, 1638, 3010},
        r"C:\Program Files\Google\Drive File Stream"
    ),
    (
        "Adobe Acrobat Reader",
        "Reader_br_install.exe",
        "/sAll /rs /msi EULA_ACCEPT=YES",
        {0, 3010, 1641},
        r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe"
    ),
    (
        "Slack",
        "Slack.msix",
        "", # Instalado via Add-AppxPackage
        {0},
        None # MSIX é difícil de detectar por caminho fixo, winget/powershell lidam com isso
    ),
    (
        "Microsoft 365",
        "OfficeSetup.exe",
        "",
        {0, 1603, 3010},
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE"
    ),
]

# ─────────────────────────────────────────────
#  FILA SSE
# ─────────────────────────────────────────────
_sse_queues: List[queue.Queue] = []
_sse_lock = threading.Lock()


def _broadcast(event: dict):
    with _sse_lock:
        for q in _sse_queues:
            q.put(event)


# ══════════════════════════════════════════════
#  SERVIDOR HTTP
# ══════════════════════════════════════════════

class AgenteHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Garante que o diretório base seja o local onde os arquivos foram extraídos (_MEIPASS)
        super().__init__(*args, directory=str(_BASE_DIR), **kwargs)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/api/stream":
            self._handle_sse()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/execute":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            params = {}
            if post_data:
                try:
                    params = json.loads(post_data.decode("utf-8"))
                except Exception:
                    pass
            
            instalar = params.get("instalar_softwares", True)
            otimizar = params.get("otimizacao", True)
            sw_lista = params.get("softwares_selecionados", [])
            
            threading.Thread(target=run_automation, args=(instalar, otimizar, sw_lista), daemon=True).start()
            self._json_response({"ok": True})
        else:
            self.send_error(404)

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type",  "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection",    "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q: queue.Queue = queue.Queue()
        with _sse_lock:
            _sse_queues.append(q)

        try:
            while True:
                try:
                    event = q.get(timeout=20)
                    data  = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _sse_lock:
                _sse_queues.remove(q)

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ══════════════════════════════════════════════
#  EMISSÃO DE EVENTOS
# ══════════════════════════════════════════════

def _log(msg: str, tipo: str = "muted"):
    _broadcast({"type": "log", "msg": msg, "tipo": tipo})
    log.info(msg)


def _etapa_inicio(etapa: str, pct: int):
    _broadcast({"type": "etapa_inicio", "etapa": etapa, "pct": pct})
    _log(f"\n{'─'*52}", "muted")
    _log(f"  [ETAPA] {etapa.upper()}  ({pct}%)", "info")
    _log(f"{'─'*52}", "muted")


def _etapa_fim(etapa: str, sucesso: bool, pct: int):
    _broadcast({"type": "etapa_fim", "etapa": etapa, "sucesso": sucesso, "pct": pct})


def _sw_progress(nome: str, estado: str, pct: int = 0):
    """estado: 'baixando' | 'instalando' | 'ok' | 'erro'"""
    _broadcast({"type": "sw_progress", "nome": nome, "estado": estado, "pct": pct})


def _setup_fim(sucesso: bool):
    _broadcast({"type": "setup_fim", "sucesso": sucesso})


# ══════════════════════════════════════════════
#  UTILITÁRIOS
# ══════════════════════════════════════════════

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_and_restart() -> None:
    script = str(Path(__file__).resolve())
    python = sys.executable

    def esc(s: str) -> str:
        return s.replace("'", "''")

    ps_cmd = (
        f"$pass = ConvertTo-SecureString '{esc(_ADMIN_PASS)}' -AsPlainText -Force; "
        f"$cred = New-Object System.Management.Automation.PSCredential('{esc(_ADMIN_USER)}', $pass); "
        f"Start-Process '{esc(python)}' "
        f"-ArgumentList '\"{esc(script)}\"' "
        f"-Credential $cred -Wait -WindowStyle Normal"
    )
    log.info("Elevando privilégios para Administrador...")
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], check=False)
    sys.exit(0)


def _run_cmd(cmd: str, label: str = "", timeout: int = 300,
             ok_codes: Optional[set] = None) -> bool:
    """Executa comando e retorna True se returncode estiver em ok_codes.
    ok_codes padrão = {0}.  Passe sets adicionais para aceitar 'já instalado' etc.
    """
    if ok_codes is None:
        ok_codes = {0}
    desc = label or cmd[:80]
    _log(f"  ▶  {desc}", "info")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            stdin=subprocess.DEVNULL,          # evita travamento: sem stdin = sem espera por input
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        for line in (result.stdout or "").strip().splitlines():
            if line.strip():
                _log(f"     {line}", "muted")
        if result.returncode in ok_codes:
            if result.returncode == 0:
                _log("  ✔  Sucesso", "ok")
            else:
                _log(f"  ✔  Código {result.returncode} → considerado sucesso (ex: já instalado)", "ok")
            return True
        # Código de erro real
        for line in (result.stderr or "").strip().splitlines():
            if line.strip():
                _log(f"     {line}", "warn")
        _log(f"  ✗  Código de saída: {result.returncode}", "warn")
        return False
    except subprocess.TimeoutExpired:
        _log("  ✗  Timeout", "err")
        return False
    except Exception as exc:
        _log(f"  ✗  Exceção: {exc}", "err")
        return False

# (função _install_adobe_via_task removida — Adobe agora via download direto)

def _download_file(url: str, filename: str, nome_sw: str) -> Optional[Path]:
    dest = Path(tempfile.gettempdir()) / filename
    _log(f"  ⬇  Baixando  {filename}", "info")
    _sw_progress(nome_sw, "baixando", 0)
    try:
        # User-Agent completo evita bloqueios por servidores Google/AnyDesk
        _headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": "application/octet-stream,*/*",
        }
        req = urllib.request.Request(url, headers=_headers)
        # timeout=600 cobre arquivos grandes (Google Drive ~240 MB)
        with urllib.request.urlopen(req, timeout=600) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            final_url = resp.geturl()
            if final_url != url:
                _log(f"  ↪  Redirecionado para: {final_url}", "muted")
            if total > 0:
                _log(f"  📦  Tamanho: {total / 1024 / 1024:.1f} MB", "muted")
            downloaded = 0
            with open(dest, "wb") as out:
                while True:
                    block = resp.read(65536)
                    if not block:
                        break
                    out.write(block)
                    downloaded += len(block)
                    if total > 0:
                        pct = min(int(downloaded * 90 / total), 90)
                        _sw_progress(nome_sw, "baixando", pct)
        _log(f"  ✔  Download concluído  ({downloaded / 1024 / 1024:.1f} MB)", "ok")
        _sw_progress(nome_sw, "baixando", 90)
        return dest
    except Exception as exc:
        _log(f"  ✗  Falha no download: {exc}", "err")
        _sw_progress(nome_sw, "erro", 0)
        return None


# ══════════════════════════════════════════════
#  ETAPAS
# ══════════════════════════════════════════════

def _etapa_downloads(sw_lista: list = None) -> bool:
    _etapa_inicio("downloads", 5)
    etapa_ok = True

    if not SOFTWARES:
        _log("  Nenhum software configurado.", "muted")
        _etapa_fim("downloads", True, 30)
        return True

    for item in SOFTWARES:
        nome, filename, args = item[0], item[1], item[2]
        
        # Filtro de seleção individual
        if sw_lista is not None and nome not in sw_lista:
            _log(f"  ⏭  {nome} não selecionado. Pulando...", "muted")
            continue

        ok_codes: set = item[3] if len(item) > 3 else {0}
        detect_path: str = item[4] if len(item) > 4 else None

        _log(f"\n  → {nome}", "info")

        # --- VERIFICAÇÃO DE INSTALAÇÃO PRÉVIA ---
        if detect_path and Path(detect_path).exists():
            _log(f"  ✔  {nome} já está instalado no sistema. Pulando...", "ok")
            _sw_progress(nome, "ok", 100)
            continue

        # ── Localização do Instalador (Pasta apps/) ──
        local_path = _BASE_DIR / "apps" / filename
        extern_path = Path(sys.executable).parent / "apps" / filename
        
        arquivo = None
        if local_path.exists():
            arquivo = local_path
            _log(f"  📦  Instalador encontrado: {filename}", "ok")
        elif extern_path.exists():
            arquivo = extern_path
            _log(f"  📦  Instalador encontrado (externo): {filename}", "ok")
        
        if arquivo is None:
            _log(f"  ✗  Erro: Arquivo {filename} não encontrado na pasta 'apps'.", "err")
            # Fallback winget para Chrome/Office mesmo se o arquivo local sumir
            fallback_id = None
            if "chrome" in nome.lower(): fallback_id = "Google.Chrome"
            if "office" in nome.lower() or "microsoft 365" in nome.lower(): fallback_id = "Microsoft.Office"
            
            if fallback_id:
                _log(f"  ⚠  Tentando fallback via winget para {nome}...", "warn")
                _sw_progress(nome, "instalando", 50)
                ok_wg = _run_cmd(f"winget install --id {fallback_id} --silent --accept-package-agreements --accept-source-agreements",
                                 label=f"winget (fallback): {nome}", timeout=2400)
                if ok_wg:
                    _sw_progress(nome, "ok", 100)
                    continue

            _sw_progress(nome, "erro", 0)
            etapa_ok = False
            continue

        _sw_progress(nome, "instalando", 92)

        # Lógica especial para pacotes MSIX (Slack)
        if str(arquivo).lower().endswith(".msix"):
            cmd = f'powershell.exe -Command "Add-AppxPackage -Path \'{arquivo}\'"'
            ok = _run_cmd(cmd, label=f"Instalando {nome} (MSIX)", timeout=600)
        else:
            # Instalação padrão (.exe / .msi)
            cmd = f'"{arquivo}" {args}'
            timeout_val = 2400 if "office" in nome.lower() or "microsoft 365" in nome.lower() else 900
            ok = _run_cmd(cmd, label=f"Instalando {nome}", timeout=timeout_val, ok_codes=ok_codes)
        
        # Fallback específico para Chrome/Office se a instalação do arquivo falhar
        if not ok:
            fallback_id = None
            if "chrome" in nome.lower(): fallback_id = "Google.Chrome"
            if "microsoft 365" in nome.lower() or "office" in nome.lower(): fallback_id = "Microsoft.Office"

            if fallback_id:
                _log(f"  ⚠  Instalação manual de {nome} falhou. Tentando fallback via winget...", "warn")
                _sw_progress(nome, "instalando", 50)
                ok = _run_cmd(f"winget install --id {fallback_id} --silent --accept-package-agreements --accept-source-agreements",
                              label=f"winget (fallback): {nome}", timeout=2400, ok_codes={0, 1, 3010})

        if ok:
            _sw_progress(nome, "ok", 100)
            # Regra de Firewall para o AnyDesk (Garante conexão)
            if "anydesk" in nome.lower():
                _log("  ⚡  Liberando AnyDesk no Firewall...", "muted")
                _run_cmd(f'netsh advfirewall firewall add rule name="AnyDesk_Blue" dir=in action=allow program="{detect_path}" enable=yes', label="Firewall: AnyDesk Inbound")
                _run_cmd(f'netsh advfirewall firewall add rule name="AnyDesk_Blue" dir=out action=allow program="{detect_path}" enable=yes', label="Firewall: AnyDesk Outbound")
        else:
            _log(f"  ⚠  Instalação de {nome} pode ter falhado (verifique o log).", "warn")
            _sw_progress(nome, "erro", 0)
            etapa_ok = False
        time.sleep(2)

    _etapa_fim("downloads", etapa_ok, 30)
    return etapa_ok


def _etapa_wallpaper() -> bool:
    _etapa_inicio("wallpaper", 32)

    # ── Localizar arquivo embutido ou externo ────────────────────────────────
    candidatos: List[Path] = []
    for nome in _WALLPAPER_NAMES:
        candidatos.append(_BASE_DIR / nome)                      # _MEIPASS (embutido no exe)
        candidatos.append(Path(sys.executable).parent / nome)   # pasta do .exe (externo)

    src: Optional[Path] = None
    for c in candidatos:
        if c.exists():
            src = c.resolve()
            break

    if src is None:
        _log("  ⚠  Imagem 'Fundo de Tela.*' não encontrada. Pulando wallpaper.", "warn")
        _etapa_fim("wallpaper", False, 38)
        return False

    # ── Copiar para local PERMANENTE ─────────────────────────────────────────
    # _MEIPASS é uma pasta temporária — o wallpaper precisa estar em disco
    # fixo para o Windows manter após o exe fechar.
    import shutil
    dest_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AgenteBlue"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    try:
        shutil.copy2(src, dest)
        _log(f"  📋  Imagem copiada para: {dest}", "muted")
    except Exception as exc:
        _log(f"  ⚠  Falha ao copiar imagem: {exc} — usando caminho original", "warn")
        dest = src   # tenta mesmo assim

    wallpaper_path = str(dest)
    _log(f"  🖼  Aplicando wallpaper: {wallpaper_path}", "info")

    # ── Método 1: ctypes SystemParametersInfo (instantâneo) ──────────────────
    try:
        SPI_SETDESKWALLPAPER = 0x0014
        SPIF_UPDATEINIFILE   = 0x01
        SPIF_SENDCHANGE      = 0x02
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0,
            wallpaper_path,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
        )
        if result:
            _log("  ✔  Wallpaper aplicado com sucesso", "ok")
            _etapa_fim("wallpaper", True, 38)
            return True
    except Exception as exc:
        _log(f"  ⚠  ctypes falhou: {exc} — tentando PowerShell...", "warn")

    # ── Método 2: PowerShell (fallback) ──────────────────────────────────────
    safe_path = wallpaper_path.replace("'", "''")  # escape aspas simples
    ps = (
        "Add-Type -TypeDefinition "
        "'using System; using System.Runtime.InteropServices; "
        "public class WP { [DllImport(\"user32.dll\")] "
        "public static extern bool SystemParametersInfo(int a, int b, string c, int d); }'; "
        f"[WP]::SystemParametersInfo(0x0014, 0, '{safe_path}', 3)"
    )
    ok = _run_cmd(
        f'powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "{ps}"',
        label="Wallpaper via PowerShell",
    )
    _etapa_fim("wallpaper", ok, 38)
    return ok


def _etapa_rede() -> bool:
    _etapa_inicio("rede", 42)
    etapa_ok = True

    # ── 1. Habilitar serviços de Descoberta de Rede ─────────────────────────
    _log("\n  > Habilitando serviços de Descoberta de Rede...", "muted")
    for svc, desc in [
        ("FDResPub", "Publicação de Recursos de Descoberta de Função"),
        ("SSDPSRV",  "Descoberta SSDP"),
        ("upnphost", "Host de Dispositivo UPnP"),
        ("fdPHost",  "Host do Provedor de Descoberta de Função"),
    ]:
        _run_cmd(f'sc config "{svc}" start= auto', label=f"Serviço {svc} → auto")
        _run_cmd(f'net start "{svc}"',              label=f"Iniciar {svc}")

    # ── 2. Firewall via PowerShell — SEM -match (usa -like, sem aspas internas) ──
    _log("\n  > Habilitando regras de firewall (PowerShell)...", "muted")

    # Habilitar descoberta + compartilhamento no perfil Privado
    ps_private_on = (
        "powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "
        "\"$rules = Get-NetFirewallRule; "
        "$filtered = $rules | Where-Object { "
        "($_.Group -like '*Discovery*') -or ($_.Group -like '*Descoberta*') -or "
        "($_.Group -like '*File and Printer*') -or ($_.Group -like '*Arquivo*') }; "
        "$filtered | Where-Object { $_.Profile -band 2 } | "
        "Set-NetFirewallRule -Enabled True\""
    )
    if not _run_cmd(ps_private_on, label="Firewall: habilitar Descoberta/Compartilhamento (Privado)"):
        etapa_ok = False

    # Desabilitar descoberta no perfil Público
    ps_public_off = (
        "powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "
        "\"$rules = Get-NetFirewallRule; "
        "$filtered = $rules | Where-Object { "
        "($_.Group -like '*Discovery*') -or ($_.Group -like '*Descoberta*') }; "
        "$filtered | Where-Object { $_.Profile -band 4 } | "
        "Set-NetFirewallRule -Enabled False\""
    )
    _run_cmd(ps_public_off, label="Firewall: desabilitar Descoberta (Público)")

    # ── 3. netsh fallback PT + EN ────────────────────────────────────────────
    _log("\n  > Aplicando regras netsh (fallback PT/EN)...", "muted")
    for cmd, label in [
        ('netsh advfirewall firewall set rule group="Descoberta de Rede" new enable=Yes profile=private',
         "netsh: Descoberta de Rede → Privada ON"),
        ('netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes profile=private',
         "netsh: Network Discovery → Private ON"),
        ('netsh advfirewall firewall set rule group="Compartilhamento de Arquivo e Impressora" new enable=Yes profile=private',
         "netsh: Compartilhamento → Privada ON"),
        ('netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes profile=private',
         "netsh: File and Printer Sharing → Private ON"),
        ('netsh advfirewall firewall set rule group="Descoberta de Rede" new enable=No profile=public',
         "netsh: Descoberta de Rede → Pública OFF"),
        ('netsh advfirewall firewall set rule group="Network Discovery" new enable=No profile=public',
         "netsh: Network Discovery → Public OFF"),
        ('netsh advfirewall firewall set rule group="Compartilhamento de Arquivo e Impressora" new enable=No profile=public',
         "netsh: Compartilhamento → Pública OFF"),
        ('netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=No profile=public',
         "netsh: File and Printer Sharing → Public OFF"),
    ]:
        _run_cmd(cmd, label=label)  # não bloqueia se grupo não existir no idioma

    # ── 4. Reforço via Registro (Descoberta de Rede) ──────────────────────────
    _log("\n  > Reforçando Descoberta de Rede via Registro...", "muted")
    reg_path = r"HKLM\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters"
    _run_cmd(f'reg add "{reg_path}" /v "AllowInsecureGuestAuth" /t REG_DWORD /d 1 /f', label="Permitir Logon de Convidado Inseguro")
    
    _etapa_fim("rede", etapa_ok, 80)
    return etapa_ok


def _etapa_smb() -> bool:
    _etapa_inicio("smb", 83)
    etapa_ok = True

    _log("\n  > Via PowerShell (Set-SmbClientConfiguration)...", "muted")
    if not _run_cmd(
        'powershell.exe -ExecutionPolicy Bypass -NoProfile -Command '
        '"Set-SmbClientConfiguration -RequireSecuritySignature $false -Force"',
        label="Set-SmbClientConfiguration RequireSecuritySignature=False",
    ):
        etapa_ok = False

    _log("\n  > Via Registro do Windows...", "muted")
    base = r"HKLM\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters"
    if not _run_cmd(f'reg add "{base}" /v EnableSecuritySignature /t REG_DWORD /d 0 /f',
                    label="Registro: EnableSecuritySignature = 0"):
        etapa_ok = False
    if not _run_cmd(f'reg add "{base}" /v RequireSecuritySignature /t REG_DWORD /d 0 /f',
                    label="Registro: RequireSecuritySignature = 0"):
        etapa_ok = False

    _etapa_fim("smb", etapa_ok, 100)
    return etapa_ok


def _etapa_teste_rede() -> bool:
    _etapa_inicio("teste_rede", 95)
    caminho = r"\\NBK-SRV-TI01"
    _log(f"\n  🔍  TESTE DE BUSCA NA REDE: Verificando {caminho}...", "info")
    
    try:
        # 0. Autenticação na rede (net use) para evitar pedido de credenciais
        _log(f"  🔑  Autenticando em {caminho}...", "muted")
        # Remove conexões existentes para evitar conflitos
        subprocess.run(f'net use {caminho} /delete /y', shell=True, capture_output=True)
        # Cria nova conexão com as credenciais fornecidas
        auth_cmd = f'net use {caminho} /user:{_NET_USER} {_NET_PASS}'
        if not _run_cmd(auth_cmd, label="Login na Rede"):
            _log(f"  ✗  Falha na autenticação de rede. Verifique usuário/senha.", "warn")
            # Prossegue mesmo assim, pode ser que já tenha acesso por outro meio

        # 1. Verificação programática de existência/acesso
        if not os.path.exists(caminho):
            _log(f"  ✗  Erro: O caminho {caminho} não foi localizado ou está inacessível.", "err")
            _log("     Verifique se o servidor está ligado e se o nome está correto.", "muted")
            _etapa_fim("teste_rede", False, 100)
            return False

        # 2. Abrir para confirmação visual
        _log(f"  ✔  Acesso confirmado. Abrindo pasta por 5 segundos...", "ok")
        os.startfile(caminho)
        
        # Espera um pouco para o usuário ver
        time.sleep(5)
        
        # 3. Fechar a janela automaticamente via PowerShell (COM Shell.Application)
        # Esse comando procura janelas do explorer que apontam para o servidor e as fecha.
        ps_close = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$shell.Windows() | Where-Object { $_.LocationURL -like '*NBK-SRV-TI01*' -or $_.LocationName -like '*NBK-SRV-TI01*' } "
            "| ForEach-Object { $_.Quit() }"
        )
        subprocess.run(["powershell", "-Command", ps_close], capture_output=True)
        
        _log(f"  🔒  Pasta fechada automaticamente para segurança.", "muted")
        _etapa_fim("teste_rede", True, 100)
        return True

    except Exception as e:
        error_msg = str(e)
        if "5" in error_msg: # Access Denied no Windows
            _log(f"  ✗  ERRO DE ACESSO: Permissão negada para {caminho}.", "err")
        elif "3" in error_msg or "2" in error_msg:
            _log(f"  ✗  ERRO DE CAMINHO: Servidor {caminho} não encontrado na rede.", "err")
        else:
            _log(f"  ✗  Erro inesperado: {error_msg}", "err")
            
        _etapa_fim("teste_rede", False, 100)
        return False


def _etapa_otimizacao() -> bool:
    _etapa_inicio("otimizacao", 98)
    _log("\n  ⚡  OTIMIZAÇÃO E LIMPEZA DO WINDOWS...", "info")
    
    acoes_ok = 0
    erros_list = []
    
    try:
        espaco_inicial = shutil.disk_usage("C:").free
    except:
        espaco_inicial = 0

    # 1. Planos de Energia (Alto Desempenho)
    if _run_cmd("powercfg -setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", label="Ativar Alto Desempenho"):
        acoes_ok += 1
    
    # 2. Configurações de Energia (NUNCA desligar/suspender)
    _log("  > Configurando tempos de suspensão/vídeo para NUNCA...", "muted")
    cmds_energia = [
        "powercfg -x -monitor-timeout-ac 0",
        "powercfg -x -monitor-timeout-dc 0",
        "powercfg -x -standby-timeout-ac 0",
        "powercfg -x -standby-timeout-dc 0",
        "powercfg -x -hibernate-timeout-ac 0",
        "powercfg -x -hibernate-timeout-dc 0",
        "powercfg -h off" # Desativar Hibernação completamente
    ]
    for c in cmds_energia: _run_cmd(c, label=f"Energia: {c}")
    acoes_ok += 1

    # 3. Ajustes Visuais (Performance com Estética)
    _log("  > Ajustando efeitos visuais (mantendo sombras e seleção)...", "muted")
    # Desativar animações de janela (as que mais pesam)
    _run_cmd(r'reg add "HKCU\Control Panel\Desktop\WindowMetrics" /v MinAnimate /t REG_SZ /d 0 /f', label="Visuais: Sem Animações de Janela")
    # Desativar transparência (melhora resposta da UI)
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" /v EnableTransparency /t REG_DWORD /d 0 /f', label="Visuais: Sem Transparência")
    # Nota: Removido VisualFXSetting=2 para preservar sombras e retângulo de seleção pedidos pelo usuário
    acoes_ok += 1

    # 4. Apps em Segundo Plano
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications" /v GlobalUserDisabled /t REG_DWORD /d 1 /f', label="Desativar Apps em Segundo Plano")
    acoes_ok += 1

    # 5. Storage Sense (Sensor de Armazenamento)
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy" /v 01 /t REG_DWORD /d 1 /f', label="Ativar Storage Sense")
    acoes_ok += 1

    # 5. Limpeza de Pastas Temporárias
    _log("  > Limpando diretórios temporários...", "muted")
    pastas_limpeza = [
        os.environ.get("TEMP"),
        os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp"),
        os.path.join(os.environ.get("LocalAppData", ""), "Temp")
    ]
    
    for pasta in pastas_limpeza:
        if pasta and os.path.exists(pasta):
            try:
                # Tentativa de remover conteúdo (ignora arquivos em uso)
                for item in os.listdir(pasta):
                    item_path = os.path.join(pasta, item)
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            os.unlink(item_path)
                        elif os.path.is_dir(item_path):
                            shutil.rmtree(item_path)
                    except: continue # Arquivo em uso
            except Exception as e: erros_list.append(f"Limpeza {pasta}: {e}")
    acoes_ok += 1

    # 6. Windows Update Cache
    _log("  > Limpando Cache do Windows Update...", "muted")
    _run_cmd("net stop wuauserv", label="Parando Windows Update (Temporário)")
    _run_cmd(f'rd /s /q "{os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "SoftwareDistribution", "Download")}"', label="Limpando SoftwareDistribution")
    _run_cmd("net start wuauserv", label="Iniciando Windows Update")
    acoes_ok += 1

    # 8. Esvaziar Lixeira
    _run_cmd('powershell.exe -Command "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"', label="Esvaziar Lixeira")
    acoes_ok += 1

    # 9. Personalização Visual (Windows 11)
    _log("  > Aplicando Personalização Visual (Modo Escuro, Barra de Tarefas)...", "muted")
    
    # Ocultar Pesquisa (0=Oculto, 1=Ícone, 2=Caixa)
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Search" /v SearchboxTaskbarMode /t REG_DWORD /d 0 /f', label="Ocultar Caixa de Pesquisa")
    
    # Desativar Visão de Tarefas
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v ShowTaskViewButton /t REG_DWORD /d 0 /f', label="Desativar Visão de Tarefas")
    
    # Modo Escuro (Sistema e Apps)
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" /v SystemUsesLightTheme /t REG_DWORD /d 0 /f', label="Modo Escuro (Sistema)")
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" /v AppsUseLightTheme /t REG_DWORD /d 0 /f', label="Modo Escuro (Apps)")
    
    # Desativar Transparência
    _run_cmd(r'reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" /v EnableTransparency /t REG_DWORD /d 0 /f', label="Desativar Transparência")
    
    # Notificar Sistema
    try:
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 5000, None)
    except: pass
    
    # Reiniciar Explorer para aplicar barra de tarefas
    _log("  > Reiniciando Windows Explorer para aplicar mudanças...", "muted")
    _run_cmd("taskkill /f /im explorer.exe", label="Parar Explorer")
    _run_cmd("start explorer.exe", label="Iniciar Explorer")
    
    acoes_ok += 1

    try:
        espaco_final = shutil.disk_usage("C:").free
        liberado_mb = max(0, (espaco_final - espaco_inicial) / (1024 * 1024))
    except:
        liberado_mb = 0

    _log("\n  ✅  RELATÓRIO DE OTIMIZAÇÃO", "ok")
    _log(f"      Ações executadas com sucesso: {acoes_ok}", "muted")
    _log(f"      Espaço liberado estimado: {liberado_mb:.2f} MB", "muted")
    if erros_list:
        _log(f"      Alertas/Erros (ignorado arquivos em uso): {len(erros_list)}", "warn")

    _etapa_fim("otimizacao", True, 100)
    return True


# ══════════════════════════════════════════════
#  ORQUESTRADOR
# ══════════════════════════════════════════════

def run_automation(instalar_softwares: bool = True, otimizacao: bool = True, sw_lista: list = None):
    inicio = datetime.now()
    erros: List[str] = []

    _log("=" * 52, "muted")
    _log("  AGENTE BLUE — " + inicio.strftime("%d/%m/%Y  %H:%M:%S"), "info")
    _log(f"  Log completo: {_LOG_FILE}", "muted")
    _log("=" * 52, "muted")

    # Etapa 1: Downloads (Opcional)
    if instalar_softwares:
        if not _etapa_downloads(sw_lista):
            erros.append("downloads")
    else:
        _log("\n  [INFO] Pulando etapa de downloads conforme solicitado.", "info")
        _etapa_inicio("downloads", 5)
        _log("  Etapa ignorada pelo usuário.", "muted")
        _etapa_fim("downloads", True, 30)

    _etapa_wallpaper()          # wallpaper: falha não é crítica
    if not _etapa_rede():
        erros.append("rede")
    if not _etapa_smb():
        erros.append("smb")
    
    # Novo Teste de Rede
    _etapa_teste_rede()

    # Etapa Final: Otimização (Opcional)
    if otimizacao:
        _etapa_otimizacao()
    else:
        _log("\n  [INFO] Pulando etapa de otimização.", "info")
        _etapa_inicio("otimizacao", 90)
        _etapa_fim("otimizacao", True, 100)

    duracao = int((datetime.now() - inicio).total_seconds())
    _log("\n" + "=" * 52, "muted")
    if erros:
        _log(f"  SETUP CONCLUÍDO COM AVISOS  ({duracao}s)", "warn")
        _log(f"  Etapas com erros: {', '.join(erros)}", "warn")
        _setup_fim(False)
    else:
        _log(f"  SETUP CONCLUÍDO COM SUCESSO ✔  ({duracao}s)", "ok")
        _setup_fim(True)
    _log("=" * 52, "muted")


# ══════════════════════════════════════════════
#  ABERTURA DA JANELA
# ══════════════════════════════════════════════

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _open_app_window(url: str):
    for path in _EDGE_PATHS + _CHROME_PATHS:
        if Path(path).exists():
            subprocess.Popen([
                path, f"--app={url}",
                "--window-size=580,720",
                "--window-position=100,40",
                "--disable-extensions",
                "--no-first-run",
            ])
            return
    webbrowser.open(url)


# ══════════════════════════════════════════════
#  PONTO DE ENTRADA
# ══════════════════════════════════════════════

def main() -> None:
    log.info("=" * 52)
    log.info("  AGENTE BLUE  —  " + datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))
    log.info("=" * 52)

    if not is_admin():
        log.info("Sem privilégios de Administrador — elevando...")
        elevate_and_restart()
        return

    log.info("✔  Rodando como Administrador.")

    port   = _find_free_port()
    server = _ThreadedServer(("127.0.0.1", port), AgenteHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://127.0.0.1:{port}/index.html"
    log.info(f"Servidor local em: {url}")
    _open_app_window(url)

    log.info("Aguardando interação do usuário. Ctrl+C para encerrar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Encerrando Agente Blue.")
        server.shutdown()


if __name__ == "__main__":
    main()
