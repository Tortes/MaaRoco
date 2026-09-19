"""Ad-hoc sign the preview app and record the signed framework hashes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

app = Path(sys.argv[1]).resolve()
if app.suffix != ".app" or not (app / "Contents/Info.plist").is_file():
    raise SystemExit("Expected a prepared .app bundle")
magic = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}
for path in sorted(app.rglob("*")):
    if not path.is_file() or path.is_symlink():
        continue
    with path.open("rb") as f:
        if f.read(4) not in magic:
            continue
    path.chmod(0o755)
    subprocess.run(["codesign", "--force", "--sign", "-", str(path)], check=True)
runtime = app / "Contents/MacOS"
manifest_path = runtime / "macos-runtime-manifest.json"
manifest = json.loads(manifest_path.read_text())
manifest["unsigned_files"] = manifest["files"].copy()
manifest["files"] = {name: hashlib.sha256((runtime / name).read_bytes()).hexdigest() for name in manifest["files"]}
manifest["signing"] = "ad-hoc; not Apple notarized"
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
