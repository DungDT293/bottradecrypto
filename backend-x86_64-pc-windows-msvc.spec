import os
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespans',
    'uvicorn.lifespans.on',
    'backend',
    'backend.api',
    'backend.api.router',
    'backend.api.auth_middleware',
    'backend.runtime',
    'backend.runtime.server',
    'backend.runtime.handshake',
    'backend.events',
    'services',
    'services.trading_service',
    'services.gemini_autonomous_trader',
    'services.telegram_listener_service',
    'parser',
    'parser.signal_parser',
    'execution',
    'risk',
    'storage',
    'storage.database',
    'config',
    'config.config',
]
for mod in ['telethon', 'uvicorn', 'fastapi', 'pytz', 'psutil']:
    ret = collect_all(mod)
    datas += ret[0]
    binaries += ret[1]
    hiddenimports += ret[2]

datas.append(('desktop/dist', 'desktop/dist'))
if os.path.exists('data/channel_winrates_6_months.json'):
    datas.append(('data/channel_winrates_6_months.json', 'data'))
for pkg in ['backend', 'services', 'execution', 'risk', 'parser', 'config', 'core', 'storage', 'telegram']:
    datas.append((pkg, pkg))

a = Analysis(
    ['backend\\launcher.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='backend-x86_64-pc-windows-msvc',
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
