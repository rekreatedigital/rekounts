"""Validate the built app's metadata before offering it as a Mac test artifact."""
import argparse
import plistlib
from pathlib import Path


def check_bundle(bundle: Path):
    with (bundle / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleIdentifier"] == "com.rekreatedigital.rekounts"
    assert info["LSUIElement"] is True
    assert info["NSMicrophoneUsageDescription"].strip()
    assert info["LSMinimumSystemVersion"] == "13.0"
    assert info["CFBundleShortVersionString"]
    executable = bundle / "Contents" / "MacOS" / info["CFBundleExecutable"]
    assert executable.is_file(), f"Missing app executable: {executable}"
    icon = bundle / "Contents" / "Resources" / info["CFBundleIconFile"]
    assert icon.is_file(), f"Missing app icon: {icon}"
    assert list((bundle / "Contents").rglob("cacert.pem")), "TLS roots missing from bundle"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    check_bundle(parser.parse_args().bundle)
