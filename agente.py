"""
agente.py — Agente Blue
=======================
Automação Windows sem dependências externas.

Arquitetura:
  - Servidor HTTP local (stdlib) serve a interface HTML
  - Server-Sent Events (SSE) enviam logs em tempo real ao browser
  - Edge/Chrome abre em modo --app (janela limpa, sem abas)

Ordem de execução ao clicar em Executar:
  1. Downloads e instalações de software
  2. Configuração de Descoberta de Rede (firewall)
  3. Configuração SMB (desativar assinatura)
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
#  sys._MEIPASS é definido pelo PyInstaller quando rodando como .exe
# ─────────────────────────────────────────────
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _BASE_DIR = Path(sys._MEIPASS)          # arquivos estáticos dentro do .exe
else:
    _BASE_DIR = Path(__file__).resolve().parent

_LOG_FILE  = Path(os.environ.get("TEMP", "C:\\Temp")) / "agente_blue.log"

# ─────────────────────────────────────────────
#  LOG — console + arquivo em %TEMP%
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
#  SOFTWARES PARA DOWNLOAD / INSTALAÇÃO
#  Formato: (nome, url, nome_arquivo, args_silenciosos)
# ─────────────────────────────────────────────
SOFTWARES: List[Tuple[str, str, str, str]] = [
    # Descomente / adicione conforme necessário:
    # (
    #     "Google Chrome",
    #     "https://dl.google.com/chrome/install/ChromeStandaloneSetup64.exe",
    #     "chrome_installer.exe",
    #     "/silent /install",
    # ),
    # (
    #     "7-Zip 23.01",
    #     "https://www.7-zip.org/a/7z2301-x64.exe",
    #     "7zip_installer.exe",
    #     "/S",
    # ),
]

# ─────────────────────────────────────────────
#  FILA DE EVENTOS SSE (Python → browser)
# ─────────────────────────────────────────────
_sse_queues: List[queue.Queue] = []   # uma fila por cliente conectado
_sse_lock = threading.Lock()


def _broadcast(event: dict):
    """Envia um evento SSE para todos os clientes conectados."""
    with _sse_lock:
        for q in _sse_queues:
            q.put(event)


# ══════════════════════════════════════════════
#  SERVIDOR HTTP
# ══════════════════════════════════════════════

class AgenteHandler(http.server.SimpleHTTPRequestHandler):
    """Serve os arquivos estáticos e a API SSE."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_BASE_DIR), **kwargs)

    # Silencia os logs de requisição do servidor no console
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/api/stream":
            self._handle_sse()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/execute":
            threading.Thread(target=run_automation, daemon=True).start()
            self._json_response({"ok": True})
        else:
            self.send_error(404)

    # ── SSE ─────────────────────────────────────
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
                    # heartbeat para manter a conexão viva
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
#  FUNÇÕES DE EMISSÃO DE EVENTOS
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


def _setup_fim(sucesso: bool):
    _broadcast({"type": "setup_fim", "sucesso": sucesso})


# ══════════════════════════════════════════════
#  UTILITÁRIOS DO SISTEMA
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


def _run_cmd(cmd: str, label: str = "") -> bool:
    desc = label or cmd[:80]
    _log(f"  ▶  {desc}", "info")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        for line in (result.stdout or "").strip().splitlines():
            if line.strip():
                _log(f"     {line}", "muted")

        if result.returncode != 0:
            for line in (result.stderr or "").strip().splitlines():
                if line.strip():
                    _log(f"     {line}", "warn")
            _log(f"  ✗  Código de saída: {result.returncode}", "warn")
            return False

        _log("  ✔  Sucesso", "ok")
        return True

    except subprocess.TimeoutExpired:
        _log("  ✗  Timeout (>120 s)", "err")
        return False
    except Exception as exc:
        _log(f"  ✗  Exceção: {exc}", "err")
        return False


def _download_file(url: str, filename: str) -> Optional[Path]:
    dest = Path(tempfile.gettempdir()) / filename
    _log(f"  ⬇  Baixando  {filename}", "info")
    _log(f"     URL: {url}", "muted")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
            downloaded = 0
            while True:
                block = resp.read(8192)
                if not block:
                    break
                out.write(block)
                downloaded += len(block)
        _log(f"  ✔  Download concluído  ({downloaded / 1024:.1f} KB)", "ok")
        return dest
    except Exception as exc:
        _log(f"  ✗  Falha no download: {exc}", "err")
        return None


# ══════════════════════════════════════════════
#  ETAPAS DA AUTOMAÇÃO
# ══════════════════════════════════════════════

def _etapa_downloads() -> bool:
    _etapa_inicio("downloads", 5)
    etapa_ok = True

    if not SOFTWARES:
        _log("  Nenhum software configurado para esta etapa.", "muted")
        _etapa_fim("downloads", True, 33)
        return True

    for nome, url, filename, args in SOFTWARES:
        _log(f"\n  → {nome}", "info")
        arquivo = _download_file(url, filename)
        if arquivo is None:
            _log(f"  ⚠  Pulando {nome} — download falhou.", "warn")
            etapa_ok = False
            continue
        ok = _run_cmd(f'"{arquivo}" {args}', label=f"Instalando {nome}")
        if not ok:
            _log(f"  ⚠  Instalação de {nome} pode ter falhado.", "warn")
            etapa_ok = False
        time.sleep(2)

    _etapa_fim("downloads", etapa_ok, 33)
    return etapa_ok


def _etapa_rede() -> bool:
    _etapa_inicio("rede", 36)
    regras = [
        ('netsh advfirewall firewall set rule group="Descoberta de Rede" new enable=Yes profile=private',
         "Descoberta de Rede → Privada  ATIVADO"),
        ('netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes profile=private',
         "Network Discovery → Private  ON"),
        ('netsh advfirewall firewall set rule group="Compartilhamento de Arquivo e Impressora" new enable=Yes profile=private',
         "Compartilhamento Arquivo/Impressora → Privada  ATIVADO"),
        ('netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes profile=private',
         "File and Printer Sharing → Private  ON"),
        ('netsh advfirewall firewall set rule group="Descoberta de Rede" new enable=No profile=public',
         "Descoberta de Rede → Pública  DESATIVADO"),
        ('netsh advfirewall firewall set rule group="Network Discovery" new enable=No profile=public',
         "Network Discovery → Public  OFF"),
        ('netsh advfirewall firewall set rule group="Compartilhamento de Arquivo e Impressora" new enable=No profile=public',
         "Compartilhamento Arquivo/Impressora → Pública  DESATIVADO"),
        ('netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=No profile=public',
         "File and Printer Sharing → Public  OFF"),
    ]
    etapa_ok = True
    for cmd, label in regras:
        if not _run_cmd(cmd, label=label):
            etapa_ok = False
    _etapa_fim("rede", etapa_ok, 66)
    return etapa_ok


def _etapa_smb() -> bool:
    _etapa_inicio("smb", 70)
    etapa_ok = True

    _log("\n  > Via PowerShell (Set-SmbClientConfiguration)...", "muted")
    if not _run_cmd(
        'powershell.exe -ExecutionPolicy Bypass -Command '
        '"Set-SmbClientConfiguration -RequireSecuritySignature $false -Force"',
        label="Set-SmbClientConfiguration RequireSecuritySignature=False",
    ):
        etapa_ok = False

    _log("\n  > Via Registro do Windows (garantia)...", "muted")
    base = r"HKLM\SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters"
    if not _run_cmd(f'reg add "{base}" /v EnableSecuritySignature /t REG_DWORD /d 0 /f',
                    label="Registro: EnableSecuritySignature = 0"):
        etapa_ok = False
    if not _run_cmd(f'reg add "{base}" /v RequireSecuritySignature /t REG_DWORD /d 0 /f',
                    label="Registro: RequireSecuritySignature = 0"):
        etapa_ok = False

    _etapa_fim("smb", etapa_ok, 100)
    return etapa_ok


# ══════════════════════════════════════════════
#  ORQUESTRADOR
# ══════════════════════════════════════════════

def run_automation():
    inicio = datetime.now()
    erros: List[str] = []

    _log("=" * 52, "muted")
    _log("  AGENTE BLUE — " + inicio.strftime("%d/%m/%Y  %H:%M:%S"), "info")
    _log(f"  Log completo: {_LOG_FILE}", "muted")
    _log("=" * 52, "muted")

    if not _etapa_downloads():
        erros.append("downloads")
    if not _etapa_rede():
        erros.append("rede")
    if not _etapa_smb():
        erros.append("smb")

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
#  ABERTURA DA JANELA (Edge / Chrome --app)
# ══════════════════════════════════════════════

_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _open_app_window(url: str, title: str = "Agente Blue"):
    """Abre a URL em modo --app (sem barra de endereço). Fallback para webbrowser."""
    for path in _EDGE_PATHS + _CHROME_PATHS:
        if Path(path).exists():
            subprocess.Popen([
                path,
                f"--app={url}",
                "--window-size=580,720",
                f"--window-position=100,80",
                "--disable-extensions",
                "--no-first-run",
            ])
            return

    # Fallback: abre no browser padrão
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

    # Inicia o servidor HTTP em uma thread daemon
    port   = _find_free_port()
    server = _ThreadedServer(("127.0.0.1", port), AgenteHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://127.0.0.1:{port}/index.html"
    log.info(f"Servidor local em: {url}")

    # Abre a janela
    _open_app_window(url)

    # Mantém o processo vivo enquanto a automação pode ser executada
    log.info("Aguardando interação do usuário. Ctrl+C para encerrar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Encerrando Agente Blue.")
        server.shutdown()


if __name__ == "__main__":
    main()
