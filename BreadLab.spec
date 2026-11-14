# -*- mode: python ; coding: utf-8 -*-
# 빌드: .venv\Scripts\python -m PyInstaller --noconfirm BreadLab.spec  →  dist\BreadLab\BreadLab.exe
from PyInstaller.utils.hooks import collect_submodules

# Arduino UNO 작업 공간은 실행 중에 불러오므로 직접 포함시킵니다.
hidden = collect_submodules('arduino_lab')

a = Analysis(
    ['BreadLab.py'],
    pathex=[],
    binaries=[],
    datas=[('breadlab.ico', '.'), ('i18n_en.json', '.')],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6', 'PyQt5', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 폴더형 빌드: 실행할 때마다 압축을 풀지 않아 시작 카드가 바로 뜹니다.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BreadLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['breadlab.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='BreadLab',
)
