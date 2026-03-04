# -*- mode: python ; coding: utf-8 -*-
# F.R.A.N.K. Updater — PyInstaller spec
# Build: pyinstaller updater/frank-updater.spec
# Output: dist/frank-updater (~15MB standalone binary)

from PyInstaller.utils.hooks import collect_all

rich_datas, rich_binaries, rich_hiddenimports = collect_all('rich')
pil_datas, pil_binaries, pil_hiddenimports = collect_all('PIL')

a = Analysis(
    ['frank_updater_entry.py'],
    pathex=['..'],
    binaries=rich_binaries + pil_binaries,
    datas=rich_datas + pil_datas,
    hiddenimports=rich_hiddenimports + pil_hiddenimports + [
        'updater.frank_updater',
        'updater.frank_updater_tray',
        'gi',
        'gi.repository.Gtk',
        'gi.repository.GLib',
        'gi.repository.AyatanaAppIndicator3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'torch'],
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
    name='frank-updater',
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
