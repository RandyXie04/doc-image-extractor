# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification for PDF Toolkit / Book Converter

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Datas collection
datas = [
    ('src/web/static', 'src/web/static'),
    ('version.json', '.'),
]

# Check template.docx
if os.path.exists('src/founder_tools/template.docx'):
    datas.append(('src/founder_tools/template.docx', 'src/founder_tools'))

# Hidden imports for FastAPI, Uvicorn, WebView, PyMuPDF
hidden_imports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'multipart',
    'multipart.multipart',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'fitz',
    'pymupdf',
    'pypandoc',
    'PIL',
    'cv2',
    'numpy',
    'docx',
]

a = Analysis(
    ['app_window.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDF_Toolkit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True, # Set console=True for troubleshooting and log viewing
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PDF_Toolkit',
)
