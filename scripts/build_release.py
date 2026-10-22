#!/usr/bin/env python3
"""Recompile the device-tested Java 1.4 helper and verify the shared Kindle 3/4 release.

Release CI uses Java 17 (java and jarsigner) and requirements.txt dependencies.
The ordinary make_launcher.py CLI does not need Java or these compiler downloads.
config.k3.json is the shared release configuration; its filename is historical.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "build" / "tools"
CLASSES = ROOT / "build" / "classes"
DIST = ROOT / "dist"
HELPER = "com/mobileread/ixtab/kindlelauncher/AutoExit.class"
MAIN = "com/mobileread/ixtab/kindlelauncher/KualKindlet.class"
ECJ_URL = "https://repo.maven.apache.org/maven2/org/eclipse/jdt/ecj/3.33.0/ecj-3.33.0.jar"
ECJ_SHA256 = "f7686c4960cf70c2ebc5c500a73a8cfc04541b730c18f1c5c21329889b137f45"
# Resolved through the GitHub commits API for lib/kdk.jar, then the contents API
# at this commit. Never download from a mutable branch or tag.
KDK_COMMIT = "e3f55e2f5745a43f52b64c854e3ee911e71bef5c"
KDK_URL = f"https://raw.githubusercontent.com/vdp/KindleTERM/{KDK_COMMIT}/lib/kdk.jar"
KDK_SHA256 = "3a51977d726bed9ad47963f7d5aa8130c7bb6473a09e978b343fa3838c3aeb37"


def download_tool(filename, url, expected_sha256):
    """Use only a SHA-256-verified download or cached copy."""
    path = TOOLS / filename
    if path.is_file():
        data = path.read_bytes()
    else:
        print(f"Downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{filename}: SHA-256 mismatch: expected {expected_sha256}, got {actual}")
    if not path.is_file():
        path.write_bytes(data)
    return path


def class_major(data, name):
    if len(data) < 8 or data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError(f"{name}: invalid class file header")
    return struct.unpack_from(">H", data, 6)[0]


def manifest_attributes(data):
    """Read the manifest main section, including folded UTF-8 headers."""
    headers = []
    for line in data.split(b"\r\n"):
        if not line:
            break
        if line.startswith(b" "):
            if not headers:
                raise ValueError("Manifest starts with a continuation line")
            headers[-1] += line[1:]
        else:
            headers.append(line)
    attrs = {}
    for header in headers:
        key, separator, value = header.partition(b": ")
        if not separator:
            raise ValueError("Malformed manifest header")
        key = key.decode("ascii")
        if key in attrs:
            raise ValueError(f"Duplicate manifest header: {key}")
        attrs[key] = value.decode("utf-8")
    return attrs


def verify_archive(path, helper_data):
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"ZIP CRC check failed: {bad_member}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Release contains duplicate ZIP entries")
        for alias in ("DNTEST", "DITEST", "DKTEST"):
            for suffix in ("SF", "RSA"):
                if f"META-INF/{alias}.{suffix}" not in names:
                    raise ValueError(f"Missing {alias}.{suffix} signature")
        config = json.loads((ROOT / "config.k3.json").read_text(encoding="utf-8"))
        attrs = manifest_attributes(archive.read("META-INF/MANIFEST.MF"))
        expected = {
            "Manifest-Version": "1.0",
            "SDK-Specification-Version": "1.0",
            "SDK-Extension-Name": "com.amazon.kindle.kindlet",
            "Extension-List": "SDK",
            "Main-Class": MAIN[:-6].replace("/", "."),
            "Implementation-Title": str(config["name"]).replace("\r", " ").replace("\n", " ").strip(),
            "Implementation-Vendor": str(config.get("vendor") or "Custom").replace("\r", " ").replace("\n", " ").strip(),
            "Implementation-Version": "1.0",
            "Amazon-Cover-Image": "KindleLauncher.jpg",
            "Toolbar-Mode": "persistent",
            "Font-Size-Mode": "point",
        }
        for key, value in expected.items():
            if attrs.get(key) != value:
                raise ValueError(f"Unexpected manifest {key}: {attrs.get(key)!r}")
        if attrs["Amazon-Cover-Image"] not in names:
            raise ValueError("Manifest cover image is missing")
        for name in names:
            if name.endswith(".class"):
                major = class_major(archive.read(name), name)
                if not 45 <= major <= 48:
                    raise ValueError(f"{name}: class major {major} is not Java 1.4 compatible")
        for name in (MAIN, HELPER):
            if class_major(archive.read(name), name) != 48:
                raise ValueError(f"{name}: expected Java 1.4 class major 48")
        if archive.read(HELPER) != helper_data:
            raise ValueError("Packaged AutoExit.class differs from the freshly compiled helper")

    # Developer certificates are self-signed: do not use -strict, which rejects
    # expected trust warnings. Still require actual JAR verification.
    result = subprocess.run(
        ["jarsigner", "-J-Duser.language=en", "-J-Duser.country=US", "-verify", str(path)],
        cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    print(result.stdout, end="", flush=True)
    if "jar verified." not in result.stdout:
        raise ValueError("jarsigner did not report a verified JAR")
    print("ZIP CRC, signatures, manifest and class versions verified.", flush=True)


def main():
    TOOLS.mkdir(parents=True, exist_ok=True)
    CLASSES.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    # A failed build must not leave a previous successful checksum file behind.
    checksums = DIST / "SHA256SUMS"
    checksums.unlink(missing_ok=True)
    ecj = download_tool("ecj-3.33.0.jar", ECJ_URL, ECJ_SHA256)
    kdk = download_tool("kdk.jar", KDK_URL, KDK_SHA256)
    reference_path = ROOT / "template" / "AutoExit.class"
    reference_data = reference_path.read_bytes()
    if class_major(reference_data, "template/AutoExit.class") != 48:
        raise ValueError("Device-tested AutoExit.class must have major version 48")
    compiled_path = CLASSES / HELPER
    compiled_path.unlink(missing_ok=True)
    subprocess.run(
        [
            "java", "-jar", str(ecj), "-source", "1.4", "-target", "1.4",
            "-g:none", "-warn:none", "-classpath",
            os.pathsep.join((str(ROOT / "template" / "base.azw2"), str(kdk))),
            "-d", str(CLASSES), "src/AutoExit.java",
        ],
        cwd=ROOT, check=True,
    )
    compiled_data = compiled_path.read_bytes()
    if class_major(compiled_data, "compiled AutoExit.class") != 48:
        raise ValueError("Compiled AutoExit.class must have major version 48")
    if compiled_data != reference_data:
        raise ValueError(
            "Recompiled AutoExit.class differs from the device-tested template; "
            "stopping without replacing it"
        )
    shutil.copyfile(compiled_path, reference_path)
    print("Recompiled AutoExit.class is byte-identical to the device-tested template.", flush=True)
    subprocess.run(
        [sys.executable, "make_launcher.py", "--config", "config.k3.json",
         "--output", "dist/KOReader.azw2"],
        cwd=ROOT, check=True,
    )
    output = DIST / "KOReader.azw2"
    verify_archive(output, compiled_data)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksums.write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(f"Release ready: {output}\n{digest}  {output.name}", flush=True)


if __name__ == "__main__":
    main()
