# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification for PDF Toolkit / Book Converter

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# Collect onnxruntime required data files and DLLs (including DirectML.dll)
ort_datas, ort_binaries, ort_hidden = collect_all('onnxruntime')

# Datas collection
datas = [
    ('src/web/static', 'src/web/static'),
    ('version.json', '.'),
]

# Check template.docx
if os.path.exists('src/founder_tools/template.docx'):
    datas.append(('src/founder_tools/template.docx', 'src/founder_tools'))

# Check bundled pandoc
if os.path.exists('bin/pandoc.exe'):
    datas.append(('bin/pandoc.exe', 'bin'))

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
    binaries=ort_binaries,
    datas=datas + ort_datas,
    hiddenimports=hidden_imports + ort_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'ultralytics', 'torch', 'torchvision', 'torchaudio', 'onnx'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filter out torch related files to prevent WinError 206 (Path too long)
a.datas = [x for x in a.datas if not ('torch' in x[0].lower() or 'torch' in x[1].lower())]
a.binaries = [x for x in a.binaries if not ('torch' in x[0].lower() or 'torch' in x[1].lower())]

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
    console=False, # Set to False to hide the black terminal window
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
