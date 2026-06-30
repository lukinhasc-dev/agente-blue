# -*- mode: python ; coding: utf-8 -*-
# AgenteBlue.spec — suporta DOIS modos de build:
#
#   ONEDIR  (padrao):  .\compilar.ps1
#       -> dist\AgenteBlue\AgenteBlue.exe + _internal\  (sem extracao / sem _MEI)
#          assets html/js/css ficam SOLTOS ao lado (editaveis sem recompilar).
#
#   ONEFILE (entrega): .\compilar.ps1 -Onefile   (define env AGENTEBLUE_ONEFILE=1)
#       -> dist\AgenteBlue.exe  (arquivo unico, comodo pro pendrive).
#          Os assets html/js/css ficam EMBUTIDOS no exe.

import os

ONEFILE = os.environ.get('AGENTEBLUE_ONEFILE') == '1'

# Assets embutidos (no onedir servem de fallback; no onefile sao a unica copia).
# config.json embutido e usado como FALLBACK: o codigo procura primeiro um
# config.json externo (ao lado do exe), editavel sem recompilar.
datas = [(f, '.') for f in ('index.html', 'script.js', 'style.css', 'config.json') if os.path.exists(f)]
if os.path.exists('bluepay-ico.ico'):
    datas.append(('bluepay-ico.ico', '.'))

# Instaladores da pasta .exe\ embutidos no executavel (build autossuficiente:
# um unico AgenteBlue.exe instala tudo sem pasta externa). Em runtime o codigo
# procura primeiro uma pasta .exe\ ao lado do exe e usa esta copia como fallback.
if os.path.isdir('.exe'):
    for _f in os.listdir('.exe'):
        if _f.lower().endswith('.exe'):
            datas.append((os.path.join('.exe', _f), '.exe'))

# Imagem de fundo embutida, se existir ao lado do projeto.
import glob as _glob
for _wp in _glob.glob('Fundo de Tela.*'):
    datas.append((_wp, '.'))

icon_file = 'bluepay-ico.ico' if os.path.exists('bluepay-ico.ico') else None

a = Analysis(
    ['agente.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

if ONEFILE:
    # Tudo dentro de um unico .exe.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='AgenteBlue',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_file,
        uac_admin=False,
    )
else:
    # Onedir: exe leve + pasta _internal ao lado.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='AgenteBlue',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_file,
        uac_admin=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='AgenteBlue',
    )
