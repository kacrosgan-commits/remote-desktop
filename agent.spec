# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['agent/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('uninstall-agent.bat', '.')],
    hiddenimports=[],
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
    name='agent',
    icon='packaging/desktop-remote-manager.ico',
    version='packaging/agent-version.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX often drops the embedded icon while leaving the display name intact.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
