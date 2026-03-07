# -*- mode: python ; coding: utf-8 -*-
# F.R.A.N.K. Recovery — PyInstaller spec
# Build: pyinstaller updater/frank-recovery.spec
# Output: dist/frank-recovery (~12MB standalone binary)

from PyInstaller.utils.hooks import collect_all

rich_datas, rich_binaries, rich_hiddenimports = collect_all('rich')

a = Analysis(
    ['frank_recovery_entry.py'],
    pathex=['..'],
    binaries=rich_binaries,
    datas=rich_datas,
    hiddenimports=rich_hiddenimports + [
        'updater.frank_recovery',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'torch', 'PIL',
              'gi', 'gi.repository'],
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
    name='frank-recovery',
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
