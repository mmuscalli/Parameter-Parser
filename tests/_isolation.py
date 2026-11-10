"""
Imported first by every test file (2026-11-09): the tests never see the user's own data. Everything the app keeps per
user -- data packs and modules made in the app, remembered variables and compounds, category edits, PubChem / arXiv
caches, local model settings -- lives in one folder (registry.default_registry_path); this points it at an empty
temporary folder for the process (removed at exit), unless the runner (scripts/run_tests.py) already gave one. The
keychain is switched off and window preferences (QSettings) go to that folder too. A test that needs user data makes it
itself there or in a temp folder of its own.
"""
import atexit
import os
import shutil
import tempfile

DATA_DIR_ENV = "PARAMETER_EXTRACTOR_DATA_DIR"      # = registry.DATA_DIR_ENV (not imported: the app isn't on the path yet)

os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")
if not os.environ.get(DATA_DIR_ENV):
    _folder = tempfile.mkdtemp(prefix="pe-test-data-")
    os.environ[DATA_DIR_ENV] = _folder
    atexit.register(shutil.rmtree, _folder, True)

# Window preferences (QSettings): a settings file in that folder, under the tests' own name -- never the app's
# ("Parameter Extractor"), and nothing carried over from an earlier test file or run.
try:
    from PySide6.QtCore import QCoreApplication, QSettings
except ImportError:                                  # no GUI installed: nothing to keep apart
    pass
else:
    QCoreApplication.setOrganizationName("ParameterExtractorTests")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      os.path.join(os.environ[DATA_DIR_ENV], "qsettings"))
