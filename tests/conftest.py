"""Suite-wide safety net: tests must never touch the developer's real data.

Most tests already pass explicit temp paths. The gap is the handful that call
``rekounts.__main__.main()`` to exercise startup hardening — ``main()`` legitimately
resolves the REAL ``%APPDATA%`` (that is its job in production), so any code
added near the top of it runs against the developer's own settings, history and
dictation log the moment a test calls it.

That is not hypothetical: the TalkativeAI -> Rekounts data migration was wired
into ``main()`` and promptly migrated the developer's live %APPDATA% during a
test run. Pinning ``APPDATA`` to a throwaway directory for the whole session
closes the hole for every current and future test, rather than asking each new
one to remember.

``paths.app_data_dir()`` reads the variable on every call, so this also covers
config.json, history.db, the log folder and the model store — and it isolates
POSIX CI too, where the fallback would otherwise be the real home directory.
"""
import pytest


@pytest.fixture(autouse=True, scope="session")
def isolate_app_data(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("APPDATA", str(tmp_path_factory.mktemp("appdata")))
    yield
    mp.undo()
