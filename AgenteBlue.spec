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
datas = [(f, '.') for f in ('index.html', 'script.js', 'style.css') if os.path.exists(f)]
if os.path.exists('img/Icone-Blue.ico'):
    datas.append(('img/Icone-Blue.ico', 'img'))

icon_file = 'img/Icone-Blue.ico' if os.path.exists('img/Icone-Blue.ico') else None

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
        console=True,
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
        console=True,
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
