"""Extract the VITURE Windows SDK from the vendor zip into vendor/ and record SHA-256 hashes.

The SDK is proprietary and is never committed. Place the official
`VITURE_XR_Glasses_SDK_for_Windows_x86_64.zip` in `sdk/` and run:

    python scripts/setup_sdk.py

Output:
    vendor/viture/windows_x86_64/bin/      DLLs (glasses.dll, ...)
    vendor/viture/windows_x86_64/include/  public headers
    vendor/viture/MANIFEST.json            zip hash, file hashes, header version
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = REPO / "sdk" / "VITURE_XR_Glasses_SDK_for_Windows_x86_64.zip"
DEST = REPO / "vendor" / "viture"
SECTIONS = {"x86_64": "bin", "include": "include"}  # zip top-level folder -> destination folder


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    args = ap.parse_args()
    if not args.zip.is_file():
        print(f"SDK zip not found: {args.zip}", file=sys.stderr)
        return 2
    zip_bytes = args.zip.read_bytes()
    out_root = DEST / "windows_x86_64"
    files: dict[str, str] = {}
    with zipfile.ZipFile(args.zip) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename).parts
            # Reject absolute paths and parent references (zip-slip protection).
            if not parts or info.filename.startswith(("/", "\\")) or any(p in ("..", "") for p in parts):
                print(f"skipping suspicious entry: {info.filename!r}", file=sys.stderr)
                continue
            if parts[0] not in SECTIONS or len(parts) != 2:
                continue
            data = zf.read(info)
            target = out_root / SECTIONS[parts[0]] / parts[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files[f"{SECTIONS[parts[0]]}/{parts[1]}"] = sha256_bytes(data)
    if "bin/glasses.dll" not in files:
        print("glasses.dll not found in the zip; is this the Windows x86_64 SDK?", file=sys.stderr)
        return 3
    version = None
    header = out_root / "include" / "viture_version.h"
    if header.is_file():
        nums = dict(re.findall(r"#define VITURE_VERSION_(MAJOR|MINOR|PATCH) (\d+)", header.read_text()))
        if len(nums) == 3:
            version = f"{nums['MAJOR']}.{nums['MINOR']}.{nums['PATCH']}"
    manifest = {
        "sdk_zip": args.zip.name,
        "sdk_zip_sha256": sha256_bytes(zip_bytes),
        "sdk_header_version": version,
        "files": dict(sorted(files.items())),
    }
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"extracted {len(files)} files, SDK header version {version}, into {out_root}")
    print(f"glasses.dll sha256 {files['bin/glasses.dll']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
