# PyInstaller recipe for the desktop app. Build with packaging/build_macos.sh
# (or: pyinstaller packaging/parameter_extractor.spec from the repo root).
#
# Produces dist/Parameter Extractor.app on macOS, or dist/Parameter Extractor/
# with "Parameter Extractor.exe" on Windows. PyInstaller doesn't cross-compile:
# build each platform's app on that platform.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "src"))
from parameter_extractor import __version__  # noqa: E402

# Developer build (build_macos.sh --dev): a separate app that also has the developer-only handoff mode
# (answering model steps in Claude Code; dev_features.py). The PUBLIC build leaves handoff.py out and
# has no DEV_BUILD marker, so that mode can't be switched on in it.
DEV = os.environ.get("PE_DEV_BUILD") == "1"
APP_NAME = "Parameter Extractor Dev" if DEV else "Parameter Extractor"
BUNDLE_ID = "io.github.parameter-extractor" + (".dev" if DEV else "")   # placeholder -- set before a signed release
datas = collect_data_files("parameter_extractor")
if DEV:
    marker = ROOT / "build" / "dev_marker" / "DEV_BUILD"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("developer build: handoff mode available\n")
    datas.append((str(marker), "parameter_extractor"))

a = Analysis(
    [str(ROOT / "packaging" / "launch_gui.py")],
    pathex=[str(ROOT / "src")],
    # prompts/*.md, schemas/*.json, gui/resources/*.png
    datas=datas,
    # imported lazily inside functions, so make sure they're bundled
    hiddenimports=["parameter_extractor.diagnostics", "pdfplumber", "pypdfium2", "anthropic",
                   "requests", "keyring"] + (["parameter_extractor.handoff"] if DEV else []),
    # numpy is needed (digitizer automation); pandas/matplotlib are not
    excludes=["tkinter", "matplotlib", "pandas", "IPython", "pytest",
              "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql",
              "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtTest"]
             + ([] if DEV else ["parameter_extractor.handoff"]),     # public build: no developer handoff
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,            # GUI app: no terminal window on Windows
    icon=str(ROOT / "packaging" / "icons" / ("app.ico" if sys.platform == "win32" else "app.icns")),
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ROOT / "packaging" / "icons" / "app.icns"),
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,   # follow light/dark mode
            "CFBundleDocumentTypes": [{               # lets users drop PDFs on the Dock icon later
                "CFBundleTypeName": "PDF document",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["com.adobe.pdf"],
            }],
        },
    )
