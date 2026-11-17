"""Create and mount-check a Mac preview DMG; does not publish or notarize it.

Run on the matching Mac architecture after building Rekounts.app:
    python -m tools.package_macos_preview
"""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import tempfile
import time

from tools.check_macos_bundle import check_bundle


def installation_notes(arch: str) -> str:
    chip = {"arm64": "Apple Silicon (M1 or newer)", "x86_64": "Intel"}[arch]
    return f"""REKOUNTS FOR MAC — PREVIEW

This download is for {chip} Macs. It requires macOS 13 or newer.
Automated checks ran on macOS 15 (Intel) and 26 (Apple Silicon).
Microphone, global hotkey and dictation into other apps still need hands-on
testing. macOS 13 and 14 have not yet been tested.

INSTALL
1. Drag Rekounts.app to the Applications shortcut in this disk image.
2. Eject the disk image. Open Rekounts from Applications.
3. This preview is not Developer ID signed or notarized by Apple. If macOS
   blocks it and you trust this download, open System Settings > Privacy &
   Security after trying to launch it, then choose Open Anyway for Rekounts.
   Managed Macs may not allow this. Follow Apple's current guidance:
   https://support.apple.com/en-us/102445
4. First launch downloads the speech model (about 486 MB). The interface
   may take a few minutes to appear. Later launches use the downloaded model.
5. In Rekounts' Permissions window, allow Microphone, Accessibility and
   Input Monitoring. Quit and reopen Rekounts after granting access.
6. Open TextEdit, click in a new document, hold Control + Command, say a
   short sentence, and release. The text should appear in your document.

No Apple Developer membership or payment is needed to use this preview.
Rekounts processes speech on your Mac; it does not upload your audio.

TEST AND REPORT
Try TextEdit, a browser text box, the Scratchpad, and a quit/reopen with
Wi-Fi off. Check that your original clipboard survives dictation.
Record the Mac chip, macOS version, and the step that succeeded or failed.
Use the Rekounts menu > Send Feedback, or:
https://github.com/rekreatedigital/rekounts/issues

Use the preview release tag and app version to identify this build.
Replacing an ad-hoc signed preview may require granting permissions again.
"""


def run(*args: str | Path) -> None:
    subprocess.run([str(arg) for arg in args], check=True)


def run_hdiutil(*args: str | Path) -> None:
    """Retry only the intermittent disk-image EBUSY error, at most five times."""
    command = ["hdiutil", *map(str, args)]
    for attempt in range(5):
        # A file avoids the diskimages-helper pipe hang described by create-dmg:
        # https://github.com/create-dmg/create-dmg/blob/master/create-dmg
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            log.seek(0)
            output = log.read()
        print(output, end="", flush=True)
        if result.returncode == 0:
            return
        if "Resource busy" not in output or attempt == 4:
            raise subprocess.CalledProcessError(result.returncode, command, output=output)
        delay = 2 ** (attempt + 1)
        print(f"Disk image resource busy; retrying in {delay}s ({attempt + 2}/5).", flush=True)
        time.sleep(delay)


def package_preview(bundle: Path, output_dir: Path) -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("Build Mac disk images on macOS.")
    arch = platform.machine()
    if arch not in ("arm64", "x86_64"):
        raise RuntimeError(f"Unsupported Mac architecture: {arch}")
    bundle = bundle.resolve(strict=True)
    check_bundle(bundle)
    executable = bundle / "Contents" / "MacOS" / "Rekounts"
    run("lipo", executable, "-verify_arch", arch)
    run("codesign", "--verify", "--deep", "--strict", bundle)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"Rekounts-macos-{arch}-preview.dmg"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")

    # Only this invocation's temporary directory is cleaned up. ditto preserves
    # framework symlinks and signature metadata; a generic copy/ZIP may not.
    with tempfile.TemporaryDirectory(prefix="rekounts-dmg-") as temporary:
        work = Path(temporary)
        stage = work / "contents"
        stage.mkdir()
        run("ditto", bundle, stage / "Rekounts.app")
        os.symlink("/Applications", stage / "Applications")
        (stage / "INSTALL.txt").write_text(installation_notes(arch), encoding="utf-8")
        dmg = work / output.name
        # -ov only applies to our own temporary image if a failed attempt left it.
        run_hdiutil("create", "-ov", "-volname", "Rekounts Preview", "-srcfolder",
                    stage, "-format", "UDZO", "-fs", "HFS+", dmg)
        run("hdiutil", "verify", dmg)
        mount = work / "mounted"
        mount.mkdir()
        run("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, dmg)
        try:
            installed = work / "installed" / "Rekounts.app"
            # Test the same copy from the mounted disk image that a user makes.
            run("ditto", mount / "Rekounts.app", installed)
            check_bundle(installed)
            run("codesign", "--verify", "--deep", "--strict", installed)
            run("lipo", installed / "Contents" / "MacOS" / "Rekounts",
                "-verify_arch", arch)
            if os.readlink(mount / "Applications") != "/Applications":
                raise RuntimeError("The Applications shortcut is missing or incorrect.")
            if (mount / "INSTALL.txt").read_text(encoding="utf-8") != installation_notes(arch):
                raise RuntimeError("The preview install guide is missing or incorrect.")
            with (installed / "Contents" / "Info.plist").open("rb") as stream:
                version = plistlib.load(stream)["CFBundleShortVersionString"]
        finally:
            run_hdiutil("detach", mount)
        # Copy only after the disk image has passed all checks.
        run("ditto", dmg, output)
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(".dmg.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"Verified preview: {output.name} (app {version}, {arch}); SHA256 {digest}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("dist/Rekounts.app"))
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    options = parser.parse_args()
    package_preview(options.bundle, options.output_dir)
