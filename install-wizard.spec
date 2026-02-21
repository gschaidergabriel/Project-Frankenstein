# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

rich_datas, rich_binaries, rich_hiddenimports = collect_all('rich')

a = Analysis(
    ['install_wizard.py'],
    pathex=[],
    binaries=rich_binaries,
    datas=[('install.sh', '.')] + rich_datas,
    hiddenimports=rich_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='frank-installer',
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
)
