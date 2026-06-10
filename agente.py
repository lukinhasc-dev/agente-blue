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
from typing import Optional, List

# ─────────────────────────────────────────────
#  CREDENCIAIS DE ADMINISTRADOR
# ─────────────────────────────────────────────
_ADMIN_USER: str = r".\Administrator"
_ADMIN_PASS: str = "Sham23*"

# ─────────────────────────────────────────────
#  CAMINHOS
# ─────────────────────────────────────────────
if getattr(sys, "frozen", False):
    # Build onedir: o .exe e os assets (html/js/css, apps/, wallpaper) ficam na
    # MESMA pasta — editáveis sem recompilar. _BUNDLE_DIR é o fallback embutido
    # (pasta _internal), usado quando um asset externo não está presente.
    _BASE_DIR = Path(sys.executable).resolve().parent
    _BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", _BASE_DIR))
else:
    _BASE_DIR = Path(__file__).resolve().parent
    _BUNDLE_DIR = _BASE_DIR

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
#  CATÁLOGO DE SOFTWARES
#  Sem instaladores embutidos. Cada app é instalado por um de dois métodos:
#    metodo="url"    → baixa o instalador oficial e roda silencioso
#                      (exe normal, ou msiexec quando "msi": True)
#    metodo="winget" → instala via Windows Package Manager (winget_id)
#  Campos:
#    nome     : rótulo (precisa bater com data-sw do index.html)
#    detect   : caminho que, se existir, indica que já está instalado (pula)
#    ok_codes : códigos de saída tratados como sucesso (padrão {0})
# ─────────────────────────────────────────────
SOFTWARES: List[dict] = [
    {
        "nome": "AnyDesk",
        "metodo": "url",
        "url": "https://download.anydesk.com/AnyDesk.exe",
        "filename": "AnyDesk.exe",
        "args": '--install "C:\\Program Files (x86)\\AnyDesk" --silent --start-with-win --create-shortcuts --create-desktop-icon',
        "ok_codes": {0, 11},
        "detect": r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe",
        "firewall": True,
    },
    {
        "nome": "Google Chrome",
        "metodo": "url",
        "url": "https://dl.google.com/chrome/install/standalonesetup64.exe",
        "filename": "ChromeStandaloneSetup64.exe",
        "args": "/silent /install",
        "ok_codes": {0, 1603, 3010},
        "detect": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    },
    {
        "nome": "Google Drive",
        "metodo": "url",
        "url": "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe",
        "filename": "GoogleDriveSetup.exe",
        "args": "--silent --desktop_shortcut --gsuite_shortcuts=false",
        "ok_codes": {0, 1638, 3010},
        "detect": r"C:\Program Files\Google\Drive File Stream",
    },
    {
        "nome": "Slack",
        "metodo": "winget",
        "winget_id": "SlackTechnologies.Slack",
        "ok_codes": {0},
        "detect": None,
    },
    {
        "nome": "Adobe Acrobat Reader",
        "metodo": "winget",
        "winget_id": "Adobe.Acrobat.Reader.64-bit",
        "ok_codes": {0},
        "detect": r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
    },
    {
        "nome": "Microsoft 365",
        "metodo": "winget",
        "winget_id": "Microsoft.Office",
        "ok_codes": {0},
        "detect": r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
    },
    {
        "nome": "WinRAR",
        "metodo": "winget",
        "winget_id": "RARLab.WinRAR",
        "ok_codes": {0},
        "detect": r"C:\Program Files\WinRAR\WinRAR.exe",
    },
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

    def translate_path(self, path):
        # Serve a partir da pasta externa (editável). Se o arquivo não existir
        # ali, cai para a cópia embutida em _internal (_BUNDLE_DIR).
        ext = super().translate_path(path)
        if os.path.exists(ext):
            return ext
        try:
            rel = os.path.relpath(ext, str(_BASE_DIR))
            cand = os.path.join(str(_BUNDLE_DIR), rel)
            if os.path.exists(cand):
                return cand
        except ValueError:
            pass
        return ext

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


def _etapa_pulada(etapa: str, pct: int):
    """Marca uma etapa como IGNORADA (não selecionada nas opções) e avança o progresso."""
    _broadcast({"type": "etapa_pulada", "etapa": etapa, "pct": pct})


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
    def esc(s: str) -> str:
        return s.replace("'", "''")

    if getattr(sys, "frozen", False):
        # Compilado: relança o próprio .exe (sem argumento de script).
        target = sys.executable
        arglist = ""
    else:
        # Dev: relança "python agente.py".
        target = sys.executable
        script = str(Path(__file__).resolve())
        arglist = f"-ArgumentList '\"{esc(script)}\"' "

    ps_cmd = (
        f"$pass = ConvertTo-SecureString '{esc(_ADMIN_PASS)}' -AsPlainText -Force; "
        f"$cred = New-Object System.Management.Automation.PSCredential('{esc(_ADMIN_USER)}', $pass); "
        f"Start-Process '{esc(target)}' "
        f"{arglist}"
        f"-Credential $cred -Wait -WindowStyle Normal"
    )
    log.info("Elevando privilégios para Administrador...")
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], check=False)
    sys.exit(0)


def _run_cmd(cmd: str, label: str = "", timeout: int = 300,
             ok_codes: Optional[set] = None, detach: bool = False) -> bool:
    """Executa comando e retorna True se returncode estiver em ok_codes.
    ok_codes padrão = {0}.  Passe sets adicionais para aceitar 'já instalado' etc.

    detach=True: NÃO captura stdout/stderr (usa DEVNULL). Necessário quando o
    comando lança um processo PERSISTENTE (explorer.exe, instaladores que abrem
    o app no fim como Google Drive/AnyDesk) — com pipes capturados, o filho herda
    o pipe e o mantém aberto, travando o Python até o timeout.
    """
    if ok_codes is None:
        ok_codes = {0}
    desc = label or cmd[:80]
    _log(f"  ▶  {desc}", "info")
    try:
        if detach:
            result = subprocess.run(
                cmd, shell=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
            )
            stdout_txt, stderr_txt = "", ""
        else:
            result = subprocess.run(
                cmd, shell=True, capture_output=True,
                stdin=subprocess.DEVNULL,      # evita travamento: sem stdin = sem espera por input
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
            stdout_txt, stderr_txt = result.stdout or "", result.stderr or ""
        for line in stdout_txt.strip().splitlines():
            if line.strip():
                _log(f"     {line}", "muted")
        if result.returncode in ok_codes:
            if result.returncode == 0:
                _log("  ✔  Sucesso", "ok")
            else:
                _log(f"  ✔  Código {result.returncode} → considerado sucesso (ex: já instalado)", "ok")
            return True
        # Código de erro real
        for line in stderr_txt.strip().splitlines():
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

# ══════════════════════════════════════════════
#  WINGET (Windows Package Manager)
# ══════════════════════════════════════════════

_WINGET_OK: Optional[bool] = None


def _winget_disponivel() -> bool:
    try:
        r = subprocess.run("winget --version", shell=True, capture_output=True,
                           text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _ensure_winget() -> bool:
    """Garante o winget. No Windows Sandbox (e Server) ele não vem instalado;
    tenta provisioná-lo via módulo Microsoft.WinGet.Client (resolve dependências
    sozinho). Resultado é cacheado. Falha não é fatal."""
    global _WINGET_OK
    if _WINGET_OK is not None:
        return _WINGET_OK

    if _winget_disponivel():
        _WINGET_OK = True
        return True

    _log("  ⚠  winget não encontrado — provisionando (necessário no Windows Sandbox)...", "warn")
    ps = (
        "[System.Net.ServicePointManager]::SecurityProtocol = "
        "[System.Net.SecurityProtocolType]::Tls12; "
        "Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null; "
        "Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery; "
        "Repair-WinGetPackageManager -Latest -Force"
    )
    _run_cmd(
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{ps}"',
        label="Instalar winget (App Installer)", timeout=900,
    )
    _WINGET_OK = _winget_disponivel()
    if not _WINGET_OK:
        _log("  ✗  Não foi possível provisionar o winget automaticamente.", "err")
    return _WINGET_OK


# ══════════════════════════════════════════════
#  CONTEXTO DO USUÁRIO LOGADO
#  O agente roda elevado como Administrator; mas todas as configurações
#  "por usuário" (wallpaper, modo escuro, barra de tarefas, %TEMP%) precisam
#  cair no perfil do usuário logado — não no do Administrator.
# ══════════════════════════════════════════════

_LOGGED_USER_CACHE = None
_LOGGED_USER_RESOLVED = False


def _logged_user() -> Optional[dict]:
    """Retorna {'user': 'PC\\Joao', 'sid': 'S-1-5-...', 'profile': 'C:\\Users\\Joao'}
    do usuário logado no console, ou None se não for possível resolver
    (ex.: rodando logado como o próprio Administrator durante testes)."""
    global _LOGGED_USER_CACHE, _LOGGED_USER_RESOLVED
    if _LOGGED_USER_RESOLVED:
        return _LOGGED_USER_CACHE
    _LOGGED_USER_RESOLVED = True

    ps = (
        "$u = (Get-CimInstance Win32_ComputerSystem).UserName; "
        "if (-not $u) { exit 1 }; "
        "$sid = (New-Object System.Security.Principal.NTAccount($u))."
        "Translate([System.Security.Principal.SecurityIdentifier]).Value; "
        "$p = (Get-ItemProperty "
        "\"HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\$sid\")"
        ".ProfileImagePath; "
        "[pscustomobject]@{user=$u; sid=$sid; profile=$p} | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        out = (r.stdout or "").strip()
        if out:
            data = json.loads(out)
            if data.get("sid") and data.get("user"):
                _LOGGED_USER_CACHE = data
                _log(f"  👤  Usuário logado detectado: {data['user']}", "muted")
    except Exception as exc:
        _log(f"  ⚠  Não foi possível detectar o usuário logado: {exc}", "warn")

    if _LOGGED_USER_CACHE is None:
        _log("  ⚠  Usuário logado não resolvido — aplicando no contexto atual (Administrator).", "warn")
    return _LOGGED_USER_CACHE


def _user_reg_base() -> str:
    """Base de registro por usuário: HKU\\<SID> do usuário logado, ou HKCU como fallback."""
    info = _logged_user()
    return f"HKU\\{info['sid']}" if info else "HKCU"


def _run_as_logged_user(cmd_path: str, label: str = "") -> bool:
    """Executa um .cmd no contexto do usuário logado via Agendador de Tarefas.
    Usa /it (token interativo do usuário logado) — não exige senha."""
    info = _logged_user()
    if not info:
        # Sem usuário resolvido: roda no contexto atual mesmo.
        return _run_cmd(f'"{cmd_path}"', label=label or "Executar script (contexto atual)")

    task = "AgenteBlue_UserApply"
    subprocess.run(f'schtasks /delete /tn {task} /f', shell=True, capture_output=True)
    create = (
        f'schtasks /create /tn {task} /tr "{cmd_path}" /sc once /st 23:59 '
        f'/ru "{info["user"]}" /it /rl limited /f'
    )
    ok = _run_cmd(create, label=f"{label} (criar tarefa no usuário)")
    if ok:
        _run_cmd(f'schtasks /run /tn {task}', label=f"{label} (executar)")
        time.sleep(4)
        subprocess.run(f'schtasks /delete /tn {task} /f', shell=True, capture_output=True)
    return ok


def _refresh_user_session(restart_explorer: bool = False, clear_recycle: bool = False) -> None:
    """Aplica as alterações por usuário (tema/wallpaper/barra de tarefas) recarregando
    os parâmetros do usuário e, opcionalmente, reiniciando o Explorer e esvaziando a
    Lixeira — tudo no contexto do usuário LOGADO."""
    info = _logged_user()

    lines = ["@echo off", "rundll32.exe user32.dll,UpdatePerUserSystemParameters 1, True"]
    if clear_recycle:
        lines.append('powershell -NoProfile -Command "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"')
    if restart_explorer:
        lines.append("taskkill /f /im explorer.exe >nul 2>&1")
        lines.append("start explorer.exe")

    if not info:
        # Fallback (contexto atual): roda os comandos direto.
        _run_cmd('rundll32.exe user32.dll,UpdatePerUserSystemParameters 1, True',
                 label="Recarregar parâmetros do usuário")
        if clear_recycle:
            _run_cmd('powershell -NoProfile -Command "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"',
                     label="Esvaziar Lixeira")
        if restart_explorer:
            _run_cmd("taskkill /f /im explorer.exe", label="Parar Explorer")
            # detach: explorer é persistente; sem isso o pipe capturado trava o Python.
            _run_cmd("start explorer.exe", label="Iniciar Explorer", detach=True)
        return

    script_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AgenteBlue"
    script_dir.mkdir(parents=True, exist_ok=True)
    cmd_file = script_dir / "refresh_user.cmd"
    try:
        cmd_file.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
        _run_as_logged_user(str(cmd_file), label="Aplicar configurações no usuário logado")
    except Exception as exc:
        _log(f"  ⚠  Falha ao aplicar no usuário logado: {exc}", "warn")


def _download_file(url: str, filename: str, nome_sw: str,
                   dest_dir: Optional[Path] = None) -> Optional[Path]:
    base = dest_dir or Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    dest = base / filename
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

def _instalar_via_url(app: dict) -> bool:
    """Baixa o instalador oficial e roda silencioso (exe ou msiexec).
    Override offline opcional: se o arquivo existir em apps/, usa-o.
    user_context=True → instala no perfil do usuário logado (apps por-usuário)."""
    nome = app["nome"]
    filename = app["filename"]
    user_ctx = bool(app.get("user_context"))

    # Apps por-usuário precisam ficar em local legível pelo usuário (ProgramData).
    dest_dir = (Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AgenteBlue"
                if user_ctx else None)

    arquivo: Optional[Path] = None
    for cand in (_BASE_DIR / "apps" / filename, Path(sys.executable).parent / "apps" / filename):
        if cand.exists():
            arquivo = cand
            _log(f"  📦  Usando instalador local (offline): {cand}", "ok")
            break

    if arquivo is None:
        arquivo = _download_file(app["url"], filename, nome, dest_dir=dest_dir)
        if arquivo is None:
            return False

    _sw_progress(nome, "instalando", 92)
    ok_codes = app.get("ok_codes", {0})
    args = app.get("args", "")

    if app.get("msi"):
        cmd = f'msiexec /i "{arquivo}" {args}'
    else:
        cmd = f'"{arquivo}" {args}'.rstrip()

    # App por-usuário: roda no contexto do usuário logado via tarefa agendada.
    if user_ctx and _logged_user():
        script_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AgenteBlue"
        script_dir.mkdir(parents=True, exist_ok=True)
        cmd_file = script_dir / "install_user_app.cmd"
        try:
            cmd_file.write_text("@echo off\r\n" + cmd + "\r\n", encoding="ascii")
        except Exception as exc:
            _log(f"  ⚠  Falha ao preparar instalação no usuário: {exc}", "warn")
            return False
        return _run_as_logged_user(str(cmd_file), label=f"Instalando {nome} (usuário logado)")

    # detach=True: instaladores podem abrir o app no fim (processo persistente)
    # e travariam o pipe capturado.
    return _run_cmd(cmd, label=f"Instalando {nome}", timeout=1800,
                    ok_codes=ok_codes, detach=True)


def _instalar_via_winget(app: dict) -> bool:
    """Instala via Windows Package Manager (winget), provisionando-o se faltar."""
    nome = app["nome"]
    _sw_progress(nome, "instalando", 50)
    if not _ensure_winget():
        _log(f"  ✗  winget indisponível — não foi possível instalar {nome}.", "err")
        return False
    cmd = (
        f"winget install --id {app['winget_id']} --exact --silent "
        "--accept-package-agreements --accept-source-agreements "
        "--disable-interactivity"
    )
    return _run_cmd(cmd, label=f"winget: {nome}", timeout=2400, ok_codes=app.get("ok_codes", {0}))


def _etapa_downloads(sw_lista: list = None) -> bool:
    _etapa_inicio("downloads", 5)
    etapa_ok = True

    if not SOFTWARES:
        _log("  Nenhum software configurado.", "muted")
        _etapa_fim("downloads", True, 30)
        return True

    for app in SOFTWARES:
        nome = app["nome"]

        # Filtro de seleção individual
        if sw_lista is not None and nome not in sw_lista:
            _log(f"  ⏭  {nome} não selecionado. Pulando...", "muted")
            continue

        _log(f"\n  → {nome}", "info")

        # Já instalado? pula.
        detect = app.get("detect")
        if detect and Path(detect).exists():
            _log(f"  ✔  {nome} já está instalado no sistema. Pulando...", "ok")
            _sw_progress(nome, "ok", 100)
            continue

        # Instala pelo método declarado.
        if app.get("metodo") == "winget":
            ok = _instalar_via_winget(app)
        else:
            ok = _instalar_via_url(app)

        if ok:
            _sw_progress(nome, "ok", 100)
            # Regra de Firewall para o AnyDesk (garante conexão).
            if app.get("firewall") and detect:
                _log("  ⚡  Liberando AnyDesk no Firewall...", "muted")
                _run_cmd(f'netsh advfirewall firewall add rule name="AnyDesk_Blue_In" dir=in action=allow program="{detect}" enable=yes', label="Firewall: AnyDesk Inbound")
                _run_cmd(f'netsh advfirewall firewall add rule name="AnyDesk_Blue_Out" dir=out action=allow program="{detect}" enable=yes', label="Firewall: AnyDesk Outbound")
        else:
            _log(f"  ⚠  Instalação de {nome} pode ter falhado (verifique o log).", "warn")
            _sw_progress(nome, "erro", 0)
            etapa_ok = False
        time.sleep(2)

    _etapa_fim("downloads", etapa_ok, 30)
    return etapa_ok


def _aplicar_wallpaper_usuario(wallpaper_path: str) -> None:
    """Aplica o wallpaper no contexto do usuário LOGADO via SystemParametersInfo
    (SPI_SETDESKWALLPAPER=20) — método correto da API do Windows, bem mais confiável
    que UpdatePerUserSystemParameters. Gera um .ps1 (P/Invoke) e o executa no usuário
    logado. Falha aqui não é crítica: o caminho já está no registro e é reaplicado no
    próximo refresh / reinício do Explorer."""
    script_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AgenteBlue"
    try:
        script_dir.mkdir(parents=True, exist_ok=True)
        ps1 = script_dir / "apply_wallpaper.ps1"
        esc_path = wallpaper_path.replace("'", "''")
        # SPI_SETDESKWALLPAPER=20, SPIF_UPDATEINIFILE|SPIF_SENDWININICHANGE=3
        ps1.write_text(
            'Add-Type @"\n'
            'using System;\n'
            'using System.Runtime.InteropServices;\n'
            'public class Wp {\n'
            '  [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]\n'
            '  public static extern int SystemParametersInfo(int a, int u, string p, int f);\n'
            '}\n'
            '"@\n'
            f"[Wp]::SystemParametersInfo(20, 0, '{esc_path}', 3) | Out-Null\n",
            encoding="utf-8",
        )
        cmd_file = script_dir / "apply_wallpaper.cmd"
        cmd_file.write_text(
            "@echo off\r\n"
            f'powershell -NoProfile -ExecutionPolicy Bypass -File "{ps1}"\r\n',
            encoding="ascii",
        )
        _run_as_logged_user(str(cmd_file), label="Aplicar wallpaper no usuário logado")
    except Exception as exc:
        _log(f"  ⚠  Falha ao aplicar wallpaper no usuário: {exc}", "warn")


def _etapa_wallpaper() -> bool:
    _etapa_inicio("wallpaper", 32)

    # ── Localizar arquivo externo (editável) ou embutido (fallback) ───────────
    # A imagem fica na subpasta img/. Procura na raiz E em img/ de cada local:
    # pasta do .exe (externo, editável) e _BUNDLE_DIR (cópia embutida no exe).
    exe_dir = Path(sys.executable).resolve().parent
    search_dirs = [
        _BASE_DIR, _BASE_DIR / "img",            # ao lado do exe / script
        exe_dir, exe_dir / "img",                # pasta do .exe (externo)
        _BUNDLE_DIR, _BUNDLE_DIR / "img",        # embutido no exe (fallback)
    ]
    src: Optional[Path] = None
    for d in search_dirs:
        for nome in _WALLPAPER_NAMES:
            cand = d / nome
            if cand.exists():
                src = cand.resolve()
                break
        if src is not None:
            break

    if src is None:
        _log("  ⚠  Imagem 'Fundo de Tela.*' não encontrada. Pulando wallpaper.", "warn")
        _etapa_fim("wallpaper", False, 38)
        return False

    # ── Copiar para local PERMANENTE e legível pelo usuário ──────────────────
    # _MEIPASS é uma pasta temporária — o wallpaper precisa estar em disco fixo.
    # ProgramData é legível por qualquer usuário (inclusive o logado não-admin).
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
    _log(f"  🖼  Aplicando wallpaper para o usuário logado: {wallpaper_path}", "info")

    # ── Escreve no hive do usuário LOGADO (não do Administrator) ──────────────
    base = _user_reg_base()
    reg_desk = f"{base}\\Control Panel\\Desktop"
    ok = _run_cmd(f'reg add "{reg_desk}" /v WallPaper /t REG_SZ /d "{wallpaper_path}" /f',
                  label="Wallpaper: caminho")
    _run_cmd(f'reg add "{reg_desk}" /v WallpaperStyle /t REG_SZ /d 10 /f',
             label="Wallpaper: estilo (Preencher)")
    _run_cmd(f'reg add "{reg_desk}" /v TileWallpaper /t REG_SZ /d 0 /f',
             label="Wallpaper: sem lado a lado")

    # Aplica imediatamente no contexto do usuário logado via SystemParametersInfo
    # (mais confiável que UpdatePerUserSystemParameters). O caminho também ficou no
    # registro, então é reforçado no próximo refresh / reinício do Explorer.
    _aplicar_wallpaper_usuario(wallpaper_path)

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

    _etapa_fim("smb", etapa_ok, 88)
    return etapa_ok



def _limpar_dir(caminho: str, timeout: int = 120) -> None:
    """Esvazia o CONTEÚDO de uma pasta (mantém a pasta em si). Best-effort:
    arquivos em uso são ignorados sem travar a execução."""
    if not caminho:
        return
    for c in (
        f'del /q /f /s "{caminho}\\*"',
        f'for /d %x in ("{caminho}\\*") do @rd /s /q "%x"',
    ):
        try:
            subprocess.run(c, shell=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            _log(f"  ⚠  Limpeza demorou demais em {caminho} (arquivos em uso).", "warn")


def _etapa_otimizacao() -> bool:
    _etapa_inicio("otimizacao", 92)
    _log("\n  ⚡  OTIMIZAÇÃO E LIMPEZA DO WINDOWS...", "info")

    acoes_ok = 0

    try:
        espaco_inicial = shutil.disk_usage("C:").free
    except Exception:
        espaco_inicial = 0

    # ── 1. Plano de Energia: Alto Desempenho (sistema, requer admin) ──────────
    if _run_cmd("powercfg -setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", label="Ativar Alto Desempenho"):
        acoes_ok += 1

    # ── 2. Energia: nunca desligar tela/suspender; desativar hibernação ───────
    _log("  > Configurando tempos de suspensão/vídeo para NUNCA...", "muted")
    for c in [
        "powercfg -x -monitor-timeout-ac 0",
        "powercfg -x -monitor-timeout-dc 0",
        "powercfg -x -standby-timeout-ac 0",
        "powercfg -x -standby-timeout-dc 0",
        "powercfg -x -hibernate-timeout-ac 0",
        "powercfg -x -hibernate-timeout-dc 0",
        "powercfg -h off",
    ]:
        _run_cmd(c, label=f"Energia: {c}")
    acoes_ok += 1

    # ── 3. Configurações POR USUÁRIO (no hive do usuário LOGADO, não do admin) ─
    base       = _user_reg_base()
    themes     = f"{base}\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"
    advanced   = f"{base}\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced"
    search     = f"{base}\\Software\\Microsoft\\Windows\\CurrentVersion\\Search"
    bgapps     = f"{base}\\Software\\Microsoft\\Windows\\CurrentVersion\\BackgroundAccessApplications"
    storage    = f"{base}\\Software\\Microsoft\\Windows\\CurrentVersion\\StorageSense\\Parameters\\StoragePolicy"
    winmetrics = f"{base}\\Control Panel\\Desktop\\WindowMetrics"

    _log("  > Aplicando ajustes visuais e de barra de tarefas no usuário logado...", "muted")
    # Animações de janela desativadas (preserva sombras/seleção)
    _run_cmd(f'reg add "{winmetrics}" /v MinAnimate /t REG_SZ /d 0 /f', label="Sem animações de janela")
    # Transparência desativada
    _run_cmd(f'reg add "{themes}" /v EnableTransparency /t REG_DWORD /d 0 /f', label="Sem transparência")
    # Modo escuro (sistema + apps)
    _run_cmd(f'reg add "{themes}" /v SystemUsesLightTheme /t REG_DWORD /d 0 /f', label="Modo escuro (sistema)")
    _run_cmd(f'reg add "{themes}" /v AppsUseLightTheme /t REG_DWORD /d 0 /f', label="Modo escuro (apps)")
    # Barra de tarefas: ocultar pesquisa e botão de Visão de Tarefas
    _run_cmd(f'reg add "{search}" /v SearchboxTaskbarMode /t REG_DWORD /d 0 /f', label="Ocultar caixa de pesquisa")
    _run_cmd(f'reg add "{advanced}" /v ShowTaskViewButton /t REG_DWORD /d 0 /f', label="Desativar Visão de Tarefas")
    # Mostrar PERCENTUAL DA BATERIA na barra de tarefas (notebooks)
    _run_cmd(f'reg add "{advanced}" /v IsBatteryPercentageEnabled /t REG_DWORD /d 1 /f', label="Mostrar % da bateria")
    # Apps em segundo plano desativados
    _run_cmd(f'reg add "{bgapps}" /v GlobalUserDisabled /t REG_DWORD /d 1 /f', label="Desativar apps em segundo plano")
    # Sensor de Armazenamento (limpeza automática)
    _run_cmd(f'reg add "{storage}" /v 01 /t REG_DWORD /d 1 /f', label="Ativar Storage Sense")
    acoes_ok += 1

    # ── 4. Limpeza de temporários e caches (USUÁRIO LOGADO + sistema) ──────────
    _log("  > Limpando temporários e caches (usuário + sistema)...", "muted")
    info = _logged_user()
    user_local = (f"{info['profile']}\\AppData\\Local" if info
                  else os.environ.get("LOCALAPPDATA", r"C:\Windows\Temp"))

    # Pastas cujo conteúdo é seguro apagar (o Windows recria o que precisar).
    pastas_limpeza = [
        f"{user_local}\\Temp",                                    # %TEMP% do usuário
        r"C:\Windows\Temp",                                       # TEMP do sistema
        r"C:\Windows\Prefetch",                                   # prefetch (recriado pelo Windows)
        f"{user_local}\\Microsoft\\Windows\\INetCache",          # cache de internet (legado)
        f"{user_local}\\CrashDumps",                             # despejos de memória de apps
        r"C:\ProgramData\Microsoft\Windows\WER\ReportQueue",     # relatórios de erro (fila)
        r"C:\ProgramData\Microsoft\Windows\WER\ReportArchive",   # relatórios de erro (arquivo)
    ]
    for p in pastas_limpeza:
        _limpar_dir(p, timeout=120)

    # Cache de miniaturas/ícones (alguns ficam em uso até reiniciar o Explorer)
    for c in (
        f'del /q /f "{user_local}\\Microsoft\\Windows\\Explorer\\thumbcache_*.db"',
        f'del /q /f "{user_local}\\Microsoft\\Windows\\Explorer\\iconcache_*.db"',
    ):
        try:
            subprocess.run(c, shell=True, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            pass

    # Flush do cache DNS e limpeza do cache de Otimização de Entrega.
    _run_cmd("ipconfig /flushdns", label="Limpar cache DNS", timeout=30)
    _run_cmd(
        'powershell -NoProfile -Command '
        '"Delete-DeliveryOptimizationCache -Force -ErrorAction SilentlyContinue"',
        label="Limpar cache de Otimização de Entrega", timeout=120,
    )
    acoes_ok += 1

    # ── 5. Cache do Windows Update ────────────────────────────────────────────
    _log("  > Limpando cache do Windows Update...", "muted")
    _run_cmd("net stop wuauserv /y", label="Parar Windows Update", timeout=15)
    _run_cmd(r'rd /s /q "C:\Windows\SoftwareDistribution\Download"', label="Limpar cache de download", timeout=30)
    _run_cmd("net start wuauserv", label="Reiniciar Windows Update", timeout=15)
    acoes_ok += 1

    # ── 5b. Limpeza profunda do armazenamento de componentes (WinSxS) ─────────
    # StartComponentCleanup remove versões antigas de componentes/atualizações.
    # É seguro (não quebra o Windows), mas pode levar alguns minutos.
    _log("  > Limpeza profunda de componentes (WinSxS) — pode levar alguns minutos...", "muted")
    _run_cmd("dism /online /cleanup-image /startcomponentcleanup",
             label="DISM: StartComponentCleanup", timeout=1800)
    acoes_ok += 1

    # ── 6. Aplicar tudo no usuário logado: tema/wallpaper + barra + lixeira ────
    _log("  > Aplicando alterações e reiniciando o Explorer no usuário logado...", "muted")
    _refresh_user_session(restart_explorer=True, clear_recycle=True)
    acoes_ok += 1

    try:
        espaco_final = shutil.disk_usage("C:").free
        liberado_mb = max(0, (espaco_final - espaco_inicial) / (1024 * 1024))
    except Exception:
        liberado_mb = 0

    _log("\n  ✅  RELATÓRIO DE OTIMIZAÇÃO", "ok")
    _log(f"      Ações executadas: {acoes_ok}", "muted")
    _log(f"      Espaço liberado estimado: {liberado_mb:.2f} MB", "muted")

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

    # ── Etapa 1: Instalação de softwares (independente das demais) ────────────
    if instalar_softwares:
        if not _etapa_downloads(sw_lista):
            erros.append("downloads")
    else:
        _log("\n  [INFO] Instalação de softwares não selecionada — pulando.", "info")
        _etapa_pulada("downloads", 30)

    # ── Etapa 2: Otimização + Personalização (wallpaper, rede, SMB, limpeza) ──
    # Tudo isto só roda quando a opção "Otimização do Windows" está marcada.
    if otimizacao:
        _etapa_wallpaper()              # wallpaper: falha não é crítica
        if not _etapa_rede():
            erros.append("rede")
        if not _etapa_smb():
            erros.append("smb")
        _etapa_otimizacao()
    else:
        _log("\n  [INFO] Otimização não selecionada — pulando personalização, rede, SMB e limpeza.", "info")
        for _et, _pct in (("wallpaper", 38), ("rede", 80), ("smb", 88), ("otimizacao", 100)):
            _etapa_pulada(_et, _pct)

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
