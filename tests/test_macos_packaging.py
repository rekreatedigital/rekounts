"""A busy image tool may retry; broken packages must still fail the build."""
import subprocess

import pytest

from tools import package_macos_preview as packaging


def fake_process(monkeypatch, responses):
    attempts, delays = [], []
    iterator = iter(responses)

    def execute(command, *, stdout, stderr, timeout):
        attempts.append(command)
        code, output = next(iterator)
        stdout.write(output)
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(packaging.subprocess, "run", execute)
    monkeypatch.setattr(packaging.time, "sleep", delays.append)
    return attempts, delays


def test_busy_disk_image_retries_then_succeeds(monkeypatch):
    attempts, delays = fake_process(monkeypatch, [
        (1, "hdiutil: create failed - Resource busy\n"), (0, "created\n"),
    ])
    packaging.run_hdiutil("create", "preview.dmg")
    assert len(attempts) == 2
    assert delays == [2]


def test_other_packaging_errors_fail_immediately(monkeypatch):
    attempts, delays = fake_process(monkeypatch, [(1, "No space left on device\n")])
    with pytest.raises(subprocess.CalledProcessError, match="non-zero exit"):
        packaging.run_hdiutil("create", "preview.dmg")
    assert len(attempts) == 1
    assert delays == []


def test_persistent_busy_error_fails_after_five_attempts(monkeypatch):
    attempts, delays = fake_process(monkeypatch, [(16, "Resource busy\n")] * 5)
    with pytest.raises(subprocess.CalledProcessError):
        packaging.run_hdiutil("detach", "/temporary/mount")
    assert len(attempts) == 5
    assert delays == [2, 4, 8, 16]
