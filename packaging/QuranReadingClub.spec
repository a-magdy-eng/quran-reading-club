# PyInstaller spec: one-folder Windows build with a windowed launcher.
# Build with:  powershell -ExecutionPolicy Bypass -File build.ps1
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"

datas = [
    (str(BACKEND / "app" / "quran_data"), "app/quran_data"),
    (str(ROOT / "frontend" / "dist"), "frontend_dist"),
]
datas += collect_data_files("tzdata")

hiddenimports = collect_submodules("uvicorn") + collect_submodules("tzdata") + ["sqlalchemy.dialects.sqlite"]

a = Analysis(
    [str(BACKEND / "run_club.py")],
    pathex=[str(BACKEND)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "httpx", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QuranReadingClub",
    console=False,
    icon=str(Path(SPECPATH) / "app.ico"),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="QuranReadingClub")
