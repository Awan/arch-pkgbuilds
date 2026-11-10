#!/usr/bin/env python3
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

INDEX_URL = (
    "https://dl.google.com/linux/chrome/deb/dists/stable/main/binary-amd64/Packages"
)
PACKAGE_NAME = "google-chrome-stable"
FILENAME_PREFIX = "pool/main/g/google-chrome-stable/google-chrome-stable_"
PACKAGE_DIR = Path(__file__).resolve().parent
PKGBUILD = PACKAGE_DIR / "PKGBUILD"
SRCINFO = PACKAGE_DIR / ".SRCINFO"


def fetch_release():
    with urllib.request.urlopen(INDEX_URL, timeout=30) as response:
        index = response.read().decode("utf-8")

    for stanza in re.split(r"\n\s*\n", index):
        fields = {}
        for line in stanza.splitlines():
            if line and not line[0].isspace() and ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value

        if (
            fields.get("Package") != PACKAGE_NAME
            or fields.get("Architecture") != "amd64"
        ):
            continue

        version_match = re.fullmatch(r"(\d+(?:\.\d+)+)-(\d+)", fields.get("Version", ""))
        if not version_match:
            raise ValueError("Google package index returned an unexpected version")

        deb_version = fields["Version"]
        expected_filename = f"{FILENAME_PREFIX}{deb_version}_amd64.deb"
        if fields.get("Filename") != expected_filename:
            raise ValueError("Google package index returned an unexpected filename")

        checksum = fields.get("SHA256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Google package index returned an invalid SHA-256")

        return version_match.group(1), int(version_match.group(2)), checksum

    raise ValueError("Google stable amd64 package was not found in the index")


def setting(text, name):
    matches = re.findall(rf"^{re.escape(name)}=(.*)$", text, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name}= setting in PKGBUILD")
    return matches[0]


def replace_setting(text, name, value):
    updated, count = re.subn(
        rf"^{re.escape(name)}=.*$",
        f"{name}={value}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(f"Expected exactly one {name}= setting in PKGBUILD")
    return updated


def version_key(version, revision):
    return tuple(int(part) for part in version.split(".")) + (revision,)


def update():
    latest_version, latest_revision, latest_checksum = fetch_release()
    original = PKGBUILD.read_text(encoding="utf-8")

    current_version = setting(original, "pkgver")
    current_revision = int(setting(original, "_deb_revision"))
    checksum_match = re.fullmatch(
        r"\('([0-9a-f]{64})'\)", setting(original, "sha256sums")
    )
    if not checksum_match:
        raise ValueError("Expected one quoted SHA-256 in sha256sums")
    current_checksum = checksum_match.group(1)

    latest_key = version_key(latest_version, latest_revision)
    current_key = version_key(current_version, current_revision)
    if latest_key < current_key:
        print(
            f"No newer release in Google's index "
            f"(index: {latest_version}-{latest_revision}, "
            f"recipe: {current_version}-{current_revision})"
        )
        return
    if latest_key == current_key:
        if latest_checksum != current_checksum:
            raise ValueError(
                "The checksum changed without a version change; refusing to update"
            )
        print(f"Already up to date: {current_version}")
        return

    updated = replace_setting(original, "pkgver", latest_version)
    updated = replace_setting(updated, "_deb_revision", str(latest_revision))
    updated = replace_setting(updated, "pkgrel", "1")
    updated = replace_setting(updated, "sha256sums", f"('{latest_checksum}')")
    PKGBUILD.write_text(updated, encoding="utf-8")

    try:
        result = subprocess.run(
            ["makepkg", "--printsrcinfo"],
            cwd=PACKAGE_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        PKGBUILD.write_text(original, encoding="utf-8")
        detail = getattr(error, "stderr", None) or str(error)
        raise RuntimeError(f"Could not regenerate .SRCINFO: {detail.strip()}") from error

    SRCINFO.write_text(result.stdout, encoding="utf-8")
    print(f"Updated Chrome Stable: {current_version} -> {latest_version}")
    print("Review the PKGBUILD and .SRCINFO, then commit and push when ready.")


if __name__ == "__main__":
    try:
        update()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"update failed: {error}", file=sys.stderr)
        sys.exit(1)
