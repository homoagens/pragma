# pragma.spec — PyInstaller build spec for Pragma (single-file .exe)
#
# Build:  run build.bat   (or:  pyinstaller --noconfirm --clean pragma.spec)
# Output: dist/pragma.exe  — a single self-contained executable.
#
# ─────────────────────────────────────────────────────────────────────────
# WHY THIS SPEC IS NOT TRIVIAL — two Pragma-specific traps:
#
# 1. Dynamic skill loading. core/skills/__init__.py scans the skills folder
#    with importlib at runtime. PyInstaller's static analysis cannot see
#    those modules, so the whole core/ tree travels as DATA (real files on
#    disk inside the bundle), not as frozen modules.
#
# 2. String entrypoint. run.py calls uvicorn.run("agent.server:app") — an
#    import-by-string PyInstaller does NOT follow. So agent.server and its
#    whole dependency chain are declared explicitly in `hiddenimports`.
#
# ─────────────────────────────────────────────────────────────────────────
# MAINTENANCE: if the built exe crashes at startup with
#   ModuleNotFoundError: No module named 'X'
# just add 'X' to the `hiddenimports` list below and rebuild. That error
# means a dependency is reached only through a dynamic import.
# ─────────────────────────────────────────────────────────────────────────

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

ROOT = Path(SPECPATH)  # SPECPATH = directory of this .spec file (injected by PyInstaller)


# ── Data: files that must exist ON DISK inside the bundle ───────────────────
def _tree(src_dir: str):
    """Collect a directory tree as (src, dest) data tuples, skipping caches."""
    out = []
    base = ROOT / src_dir
    for f in base.rglob("*"):
        if not f.is_file():
            continue
        if "__pycache__" in f.parts or f.suffix in (".pyc", ".pyo"):
            continue
        # To EXCLUDE the experimental skills from the trial exe, uncomment:
        # if any(p.startswith("wip_") for p in f.parts):
        #     continue
        out.append((str(f), str(f.parent.relative_to(ROOT))))
    return out


datas  = _tree("core")            # config, skills, react.py, llm_client, ...
datas += _tree("interface-web")   # the web UI (HTML/JS/CSS)
datas += collect_data_files("certifi")  # CA bundle needed by the HTTPS stack


# ── Hidden imports: modules reached only via string / dynamic import ────────
hiddenimports = [
    # trap 2: the string entrypoint chain
    "agent.server", "agent.run", "agent.prompts",
    # core modules added to sys.path at runtime by server.py
    "config", "memory", "llm_client", "json_parser",
    # third-party deps used inside dynamically-loaded skills / core
    "paramiko", "requests", "anthropic", "dotenv", "rich",
    "json_repair", "websockets", "pydantic",
]
hiddenimports += collect_submodules("uvicorn")    # uvicorn loads workers/loops dynamically
hiddenimports += collect_submodules("anthropic")
hiddenimports += collect_submodules("fastapi")


# ── Packages imported lazily INSIDE dynamically-loaded skills ───────────────
# A skill that does `from X import ...` inside its function body is invisible
# to static analysis (the skill files travel as data, not as frozen modules).
# collect_all pulls in each package's modules + data files + compiled binaries.
#   ddgs   -> the web_search skill (`from ddgs import DDGS`)
#   lxml   -> ddgs dependency (HTML parsing, compiled extension)
#   primp  -> ddgs dependency (Rust-based HTTP client, compiled extension)
#   click  -> ddgs dependency
# If another skill fails in the exe with ModuleNotFoundError, add its
# top-level package to this list.
binaries = []
for _pkg in ("ddgs", "lxml", "primp", "click"):
    _d, _b, _h = collect_all(_pkg)
    datas        += _d
    binaries     += _b
    hiddenimports += _h


a = Analysis(
    ["agent/run.py"],
    pathex=[str(ROOT), str(ROOT / "core")],  # so `import config`, `from skills ...` resolve
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Single-file build: binaries + datas go straight into EXE, no COLLECT step.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pragma",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX can corrupt some DLLs; keep off for reliability
    runtime_tmpdir=None,
    console=True,         # run.py prints the server URL on stdout — keep a console
    disable_windowed_traceback=False,
)
