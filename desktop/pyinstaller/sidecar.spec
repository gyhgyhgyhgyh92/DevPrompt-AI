# -*- mode: python ; coding: utf-8 -*-
"""DevPrompt AI 桌面端 sidecar 打包规格（PyInstaller 6.22.3，版本经 PyPI 核实，MUST-24b）。

入口 src/devprompt_ai/desktop.py：绑定随机端口起 uvicorn，stdout 单行就绪协议。
one-dir 产物（dist/devprompt-ai-desktop/）由 desktop/scripts/build-desktop.py
搬进安装包 resources/sidecar/。

console=True 是硬约束：sidecar 的 stdout/stderr 就是与 Electron 主进程的协议通道，
窗口化（windowed）会让管道拿不到输出，主进程 30s 超时后误判「未就绪」。

三平台适配：Windows 版本资源（PE 元数据，抑制杀软误报）仅在 Windows 生成；
macOS 专属的签名/argv 模拟参数仅在 macOS 传入；其余平台参数按 PyInstaller
文档的适用范围条件化，避免在不适用的平台上触发校验错误。
"""

import os
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

REPO_ROOT = Path(os.path.abspath(os.path.join(SPECPATH, '..', '..'))).resolve()
ENTRY = REPO_ROOT / 'src' / 'devprompt_ai' / 'desktop.py'

IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'

# 版本号唯一来源 pyproject.toml（与安装包同源，不手抄，MUST-03）
_VERSION = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project'][
    'version'
]
_VERSION_TUPLE = tuple(int(p) for p in (_VERSION.split('.') + ['0', '0', '0', '0'])[:4])
_VERSION_STR = '.'.join(str(p) for p in _VERSION_TUPLE)

# 版本资源：杀软对「无元数据的匿名打包二进制」误报率显著更高（PyInstaller bootloader
# 是被滥用最多的打包器之一）。嵌入 ProductName/Company/OriginalFilename 后，
# SmartScreen 与 Defender 的启发式扫描有据可依——这是不买代码签名证书前提下
# 性价比最高的一步。one-dir + 禁 UPX 已在规格里，勿回退。
# PE 版本资源是 Windows 专属格式，其他平台不生成（PyInstaller 的 version= 亦仅 Windows 生效）。
_VERSION_FILE = REPO_ROOT / '.tmp' / 'sidecar-version-info.txt'
if IS_WINDOWS:
    _VERSION_INFO_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vt},
    prodvers={vt},
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [
          StringStruct('CompanyName', 'DevPrompt AI'),
          StringStruct('FileDescription', 'DevPrompt AI desktop sidecar'),
          StringStruct('FileVersion', '{vs}'),
          StringStruct('InternalName', 'devprompt-ai-desktop'),
          StringStruct('LegalCopyright', 'MIT License'),
          StringStruct('OriginalFilename', 'devprompt-ai-desktop.exe'),
          StringStruct('ProductName', 'DevPrompt AI'),
          StringStruct('ProductVersion', '{vs}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [0x804, 1200])])
  ]
)
"""
    _VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    _VERSION_FILE.write_text(
        _VERSION_INFO_TEMPLATE.format(vt=repr(_VERSION_TUPLE), vs=_VERSION_STR), encoding='utf-8'
    )

# uvicorn 的协议/循环实现按可用性自动选择（httptools/websockets 未装则回落 h11/asyncio），
# 选择逻辑的 import 发生在函数体内；h11 是 httpx→httpcore 的既有依赖，必然在场。
# agents（openai-agents）与项目自身的适配器按子模块全收：宁可多打不可漏打——
# 漏一个 import 的后果是 end-user 机器上运行时才崩，而非构建时。
hiddenimports = [
    'uvicorn',
    'uvicorn.lifespan.on',
    'uvicorn.protocols.http.h11_impl',
]
hiddenimports += collect_submodules('agents')
hiddenimports += collect_submodules('devprompt_ai')
hiddenimports += collect_submodules('uvicorn')

# agents/mcp/_compat.py 在**模块导入时**执行 importlib.metadata.version('mcp')，
# 且无兜底——PyInstaller 默认不带 dist-info 元数据，冻结包一 import 就
# PackageNotFoundError（smoke-sidecar.ps1 实测抓到的第一个 bug）。
# openai-agents 自身版本有 try/except 兜底，一并带上只为版本号准确。
datas = []
datas += copy_metadata('mcp')
datas += copy_metadata('openai-agents')
# agents/sandbox/memory/prompts.py 在 import 时按 Path(__file__).parent 读
# prompts/*.md——PyInstaller 默认只收 .py，数据文件必须显式带上
# （smoke-sidecar.ps1 实测抓到的第二个 bug；开发态有源文件故不暴露）。
datas += collect_data_files('agents')

block_cipher = None

# 平台专属参数按 PyInstaller 文档的适用范围条件化传入
_ANALYSIS_OPTS = {}
if IS_WINDOWS:
    _ANALYSIS_OPTS.update(
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
    )

_EXE_OPTS = {}
if IS_WINDOWS:
    _EXE_OPTS.update(
        version=str(_VERSION_FILE),
        disable_windowed_traceback=False,
    )
else:
    _EXE_OPTS.update(
        bootloader_ignore_signals=False,
    )
if IS_MACOS:
    _EXE_OPTS.update(
        argv_emulation=False,
        codesign_identity=None,
        entitlements_file=None,
    )

a = Analysis(
    [ENTRY],
    pathex=[os.path.join(REPO_ROOT, 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    cipher=block_cipher,
    noarchive=False,
    **_ANALYSIS_OPTS,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='devprompt-ai-desktop',
    debug=False,
    strip=False,
    upx=False,
    console=True,
    target_arch=None,
    **_EXE_OPTS,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='devprompt-ai-desktop',
)
