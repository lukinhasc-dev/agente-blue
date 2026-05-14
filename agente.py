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
SOFTWARES: List[Tuple] = [
    (
        "AnyDesk",
        "https://download.anydesk.com/AnyDesk.exe",
        "AnyDesk.exe",   # DEVE ser AnyDesk.exe — o instalador verifica o próprio nome
        '--install "C:\\Program Files (x86)\\AnyDesk" --silent --start-with-win --create-shortcuts --create-desktop-icon',
        # 11 = já instalado / serviço já em execução → tratar como sucesso
        {0, 11},
    ),
    (
        "Google Chrome",
        "https://dl.google.com/chrome/install/ChromeStandaloneSetup64.exe",
        "chrome_setup.exe",
        "/silent /install",
        # 3010 = sucesso, reinicialização necessária
        {0, 3010},
    ),
    (
        "Google Drive",
        "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe",
        "googledrive_setup.exe",
        "--silent --desktop_shortcut --skip_launch_new --gsuite_shortcuts=false",
        # 1638 = outra versão já instalada (MSI), 3010 = reinicialização necessária
        {0, 1638, 3010},
    ),
    (
        "Adobe Acrobat Reader",
        "https://ardownload2.adobe.com/pub/adobe/acrobat/win/AcrobatDC/2600121529/AcroRdrDCx642600121529_MUI.exe",
        "AcroRdrDC_setup.exe",
        "-sfx_nu /sAll /rs /msi EULA_ACCEPT=YES",
        {0, 3010, 1641},
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
            threading.Thread(target=run_automation, args=(instalar,), daemon=True).start()
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
                "Chrome/124.0.0.0 Safari/537.36"
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

def _etapa_downloads() -> bool:
    _etapa_inicio("downloads", 5)
    etapa_ok = True

    if not SOFTWARES:
        _log("  Nenhum software configurado.", "muted")
        _etapa_fim("downloads", True, 30)
        return True

    for item in SOFTWARES:
        # Suporte a 4-tupla (legado) e 5-tupla (com ok_codes)
        nome, url, filename, args = item[0], item[1], item[2], item[3]
        ok_codes: set = item[4] if len(item) > 4 else {0}

        _log(f"\n  → {nome}", "info")

        # (Adobe agora tem URL direta — cai no fluxo normal de download+install abaixo)

        # ── Matar processos conflitantes antes de instalar ──────────────────
        _kill_map = {
            "anydesk":     "anydesk.exe",
            "google drive": "googledrivesync.exe",
        }
        for kw, proc in _kill_map.items():
            if kw in nome.lower():
                subprocess.run(
                    f"taskkill /f /im {proc}",
                    shell=True, capture_output=True, timeout=10
                )
                _log(f"  🔪  Encerrando processo: {proc} (se em execução)", "muted")

        # ── winget: url vazia = sem download, executa comando diretamente ──
        if not url:
            _sw_progress(nome, "instalando", 50)
            ok = _run_cmd(args, label=f"winget: {nome}", timeout=900,
                          ok_codes=ok_codes)
            if ok:
                _sw_progress(nome, "ok", 100)
            else:
                _log(f"  ⚠  winget falhou para {nome}.", "warn")
                _sw_progress(nome, "erro", 0)
                etapa_ok = False
            time.sleep(1)
            continue

        # ── download + instalação normal ──
        arquivo = _download_file(url, filename, nome)
        if arquivo is None:
            _log(f"  ⚠  Pulando {nome} — download falhou.", "warn")
            _sw_progress(nome, "erro", 0)
            etapa_ok = False
            continue

        _sw_progress(nome, "instalando", 92)
        ok = _run_cmd(f'"{arquivo}" {args}', label=f"Instalando {nome}",
                      timeout=600, ok_codes=ok_codes)
        if ok:
            _sw_progress(nome, "ok", 100)
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
    _log(f"\n  🔍  TESTE DE BUSCA NA REDE: Acessando {caminho}...", "info")
    
    try:
        # Tenta abrir o explorer diretamente no caminho
        # Se houver erro de rede, o Windows mostrará o popup, 
        # mas o comando em si 'dispara' a tentativa.
        os.startfile(caminho)
        _log(f"  ✔  Solicitação de abertura enviada para o Explorador.", "ok")
        _log(f"  💡  Se a pasta {caminho} abrir sem erros, o compartilhamento está OK!", "info")
        _etapa_fim("teste_rede", True, 100)
        return True
    except Exception as e:
        _log(f"  ✗  Erro ao tentar abrir caminho de rede: {e}", "warn")
        _etapa_fim("teste_rede", False, 100)
        return False


# ══════════════════════════════════════════════
#  ORQUESTRADOR
# ══════════════════════════════════════════════

def run_automation(instalar_softwares: bool = True):
    inicio = datetime.now()
    erros: List[str] = []

    _log("=" * 52, "muted")
    _log("  AGENTE BLUE — " + inicio.strftime("%d/%m/%Y  %H:%M:%S"), "info")
    _log(f"  Log completo: {_LOG_FILE}", "muted")
    _log("=" * 52, "muted")

    # Etapa 1: Downloads (Opcional)
    if instalar_softwares:
        if not _etapa_downloads():
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
    
    # Novo Teste de Rede ao final
    _etapa_teste_rede()

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
