# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for RemarkableSync Unified Tool
This creates a standalone executable for the unified backup and conversion tool.
"""

import sys
from pathlib import Path

block_cipher = None

# Determine platform-specific settings
if sys.platform == 'darwin':
    # macOS specific settings
    icon_file = None  # Can add .icns file here
elif sys.platform == 'win32':
    # Windows specific settings
    icon_file = None  # Can add .ico file here
else:
    icon_file = None

a = Analysis(
    ['../RemarkableSync.py'],
    pathex=['..'],
    binaries=[],
    datas=[
        # Include all src package modules
        ('../src/backup', 'src/backup'),
        ('../src/converters', 'src/converters'),
        ('../src/commands', 'src/commands'),
        ('../src/utils', 'src/utils'),
    ],
    hiddenimports=[
        'src',
        'src.__version__',
        'src.backup',
        'src.backup.backup_manager',
        'src.backup.connection',
        'src.backup.metadata',
        'src.converters',
        'src.converters.base_converter',
        'src.converters.v4_converter',
        'src.converters.v5_converter',
        'src.converters.v6_converter',
        'src.template_renderer',
        'src.converter',
        'src.hybrid_converter',
        'src.commands',
        'src.commands.backup_command',
        'src.commands.convert_command',
        'src.commands.sync_command',
        'src.utils',
        'src.utils.logging',
        'paramiko',
        'scp',
        'click',
        'tqdm',
        'cryptography',
        'pathlib2',
        'requests',
        'dateutil',
        'keyring',
        # PDF conversion dependencies
        'PyPDF2',
        'svglib',
        'reportlab',
        'reportlab.pdfgen',
        'reportlab.lib',
        'reportlab.lib.utils',
        # PIL/Pillow - required by reportlab
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ImageColor',
        'PIL._imaging',
        # Additional hidden imports for paramiko/cryptography
        'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.bindings._openssl',
        '_cffi_backend',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
    ],
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
    name='RemarkableSync',
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RemarkableSync',
)
