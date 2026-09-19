"""Download and verify the pinned macOS SDK and frontend archives."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--arch", choices=["arm64", "x64"], required=True)
parser.add_argument("--directory", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
lock = json.loads((root / "macos-dependencies.lock.json").read_text())[args.arch]
args.directory.mkdir(parents=True, exist_ok=True)
for kind, item in lock.items():
    archive = args.directory / item["url"].rsplit("/", 1)[1]
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
        subprocess.run(["curl", "--fail", "--location", "--retry", "5", "--output", str(archive), item["url"]], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit(f"Archive integrity check failed: {archive.name}")
    destination = args.directory / kind
    if destination.exists():
        raise SystemExit(f"Extraction directory already exists: {destination}; use a fresh directory")
    destination.mkdir()
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(destination)
    else:
        with tarfile.open(archive) as t:
            t.extractall(destination, filter="data")
    print(f"Verified and extracted {kind} for {args.arch}")
