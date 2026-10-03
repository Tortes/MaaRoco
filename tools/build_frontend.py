"""Build pinned MXU with MaaRoco task modes and automatic window switching."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "frontend.lock.json"


def run(*arguments, cwd=None, env=None):
    subprocess.run([str(argument) for argument in arguments], cwd=cwd, env=env, check=True)


def git(source, *arguments, check=True, env=None):
    return subprocess.run(
        ["git", "-c", f"safe.directory={source.as_posix()}", "-C", str(source), *arguments],
        check=check, capture_output=True, text=True, encoding="utf-8", env=env,
    )


def validate_source(source, patch):
    """Compare complete source trees without touching the user's Git index."""
    with tempfile.TemporaryDirectory(prefix="maaroco-mxu-source-") as directory:
        trees = []
        for name in ("expected", "actual"):
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(Path(directory) / name)
            git(source, "read-tree", "HEAD", env=environment)
            if name == "expected":
                git(source, "apply", "--cached", str(patch), env=environment)
            else:
                git(source, "add", "--all", ".", env=environment)
            trees.append(git(source, "write-tree", env=environment).stdout.strip())
        if trees[0] != trees[1]:
            raise RuntimeError("Frontend source contains changes outside the pinned patch; "
                               "preserve local edits and use a clean checkout.")


def prepare_source(source, lock):
    if not (source / ".git").exists():
        source.mkdir(parents=True, exist_ok=True)
        if any(source.iterdir()):
            raise RuntimeError(f"Frontend source directory is not an empty Git checkout: {source}")
        run("git", "init", source)
        git(source, "remote", "add", "origin", lock["repository"])
        git(source, "fetch", "--depth=1", "origin", lock["commit"])
        git(source, "checkout", "--detach", "FETCH_HEAD")
    if git(source, "rev-parse", "HEAD").stdout.strip() != lock["commit"]:
        raise RuntimeError(f"Frontend checkout must use the pinned commit {lock['commit']}: {source}")
    patch = ROOT / lock["patch"]
    if git(source, "apply", "--check", str(patch), check=False).returncode == 0:
        git(source, "apply", str(patch))
    elif git(source, "apply", "--reverse", "--check", str(patch), check=False).returncode != 0:
        raise RuntimeError(f"Frontend patch does not match {source}; preserve local edits and use a clean checkout.")
    validate_source(source, patch)


def frontend_metadata(lock):
    return {
        "flavor": lock["flavor"], "commit": lock["commit"], "target": lock["target"],
        "patch_sha256": hashlib.sha256((ROOT / lock["patch"]).read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "build/frontend/MXU")
    parser.add_argument("--output", type=Path, default=ROOT / "build/frontend/publish/mxu-win-x64")
    parser.add_argument("--pnpm-cli", type=Path, help="Path to pnpm.cjs for portable Node installations")
    parser.add_argument("--rust-bin", type=Path, help="Directory containing cargo and rustc")
    parser.add_argument("--rust-target", help="Override the locked compiler target for local builds")
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    source, output = args.source.resolve(), args.output.resolve()
    prepare_source(source, lock)
    environment = os.environ.copy()
    environment["CI"] = "true"
    environment.setdefault("CARGO_HOME", str(ROOT / "build/frontend/cargo"))
    local_rust = ROOT / "build/frontend/rustup/toolchains/1.93.0-x86_64-pc-windows-gnu/bin"
    use_local_rust = not args.rust_bin and local_rust.is_dir() and not shutil.which("cargo")
    if args.rust_bin:
        environment["PATH"] = str(args.rust_bin.resolve()) + os.pathsep + environment["PATH"]
    elif use_local_rust:
        environment["PATH"] = str(local_rust) + os.pathsep + environment["PATH"]
        environment["PATH"] = str(ROOT / "build/toolchain/llvm-mingw-20260908-ucrt-x86_64/bin") + os.pathsep + environment["PATH"]
        environment["LIBRARY_PATH"] = str(local_rust.parent / "lib/rustlib/x86_64-pc-windows-gnu/lib/self-contained")
    local_cli = ROOT / "build/frontend/pnpm10/package/bin/pnpm.cjs"
    cli = args.pnpm_cli or (local_cli if local_cli.is_file() else None)
    pnpm = [shutil.which("node") or "node", str(cli.resolve())] if cli else [shutil.which("pnpm") or "pnpm"]
    rust_target = args.rust_target or ("x86_64-pc-windows-gnu" if use_local_rust else lock["rust_target"])
    output.mkdir(parents=True, exist_ok=True)
    metadata_path = output / "maaroco-frontend.json"
    metadata_path.unlink(missing_ok=True)
    run(*pnpm, "install", "--frozen-lockfile", "--node-linker=hoisted", "--package-import-method=copy",
        "--store-dir", source / "node_modules/.pnpm-store", cwd=source, env=environment)
    run(*pnpm, "test", cwd=source, env=environment)
    # Generate branding outside the checkout, preserving its pinned patch.
    branding = json.loads((source / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    branding.update(productName="MaaRoco", identifier="com.tortes.maaroco", version=lock["version"].removeprefix("v"))
    branding["app"]["windows"][0]["title"] = "MaaRoco"
    branding["bundle"]["icon"] = [str(ROOT / "assets/locales/MaaRoco.ico")]
    config_path = ROOT / "build/frontend/maaroco-tauri.json"
    config_path.write_text(json.dumps(branding, indent=2) + "\n", encoding="utf-8")
    run(*pnpm, "exec", "tauri", "build", "--no-bundle", "--target", rust_target,
        "--config", config_path, "--", "--locked", cwd=source, env=environment)
    executable = source / f"src-tauri/target/{rust_target}/release/mxu.exe"
    shutil.copy2(executable, output / "mxu.exe")
    metadata = frontend_metadata(lock)
    metadata["compiler_target"] = rust_target
    metadata["exe_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    metadata["runtime_files"] = {}
    # MSVC links the WebView2 loader statically; the GNU crate uses its DLL.
    if rust_target == "x86_64-pc-windows-gnu":
        cargo_lock = tomllib.loads((source / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
        webview = next(package for package in cargo_lock["package"] if package["name"] == "webview2-com-sys")
        loaders = list(Path(environment["CARGO_HOME"]).glob(
            f"registry/src/*/webview2-com-sys-{webview['version']}/x64/WebView2Loader.dll"))
        if not loaders:
            raise RuntimeError("The locked GNU WebView2 loader was not found in Cargo's registry")
        loader = loaders[0]
        shutil.copy2(loader, output / "WebView2Loader.dll")
        metadata["runtime_files"]["WebView2Loader.dll"] = hashlib.sha256(loader.read_bytes()).hexdigest()
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"MaaRoco MXU frontend built at {output}")


if __name__ == "__main__":
    main()
