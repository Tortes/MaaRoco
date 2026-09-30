"""Mirror GitHub releases to Gitee, splitting files below its 100 MB limit.

Requires requests and the authenticated GitHub CLI. GITEE_TOKEN is read only
from the environment; release binaries and reports belong outside the checkout.
"""

import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import quote

PART_SIZE = 95_000_000
MARKER = "<!-- gitee-sync-source: "


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name):
    if not name or name in (".", "..") or any(char in name for char in '/\\\r\n\x00'):
        raise ValueError(f"Unsafe asset or tag name: {name!r}")
    return name


def asset_parts(asset):
    name, size = safe_name(asset["name"]), asset["size"]
    if size <= PART_SIZE:
        return [(name, size)]
    return [(f"{name}.{index + 1:03}", min(PART_SIZE, size - offset))
            for index, offset in enumerate(range(0, size, PART_SIZE))]


def split_asset(path, size_limit=PART_SIZE):
    if path.stat().st_size <= size_limit:
        return [path]
    parts = []
    with path.open("rb") as source:
        index = 1
        while chunk := source.read(size_limit):
            part = path.with_name(f"{path.name}.{index:03}")
            part.write_bytes(chunk)
            parts.append(part)
            index += 1
    return parts


def fingerprint(release):
    assets = [{key: item.get(key) for key in ("id", "name", "size", "digest", "updated_at")}
              for item in release["assets"]]
    return hashlib.sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest()


def download_notes(release):
    lines = ["# Gitee 分卷下载说明", "", "Gitee 单附件上限为 100 MB，大文件已按 95 MB 分卷。",
             "下载同一个安装包的全部分卷到同一目录，合并后得到与 GitHub 完全相同的原始文件。",
             "不要分别解压分卷。合并完成并通过 SHA-256 校验后，再解压原始 ZIP。", ""]
    for asset in release["assets"]:
        parts = asset_parts(asset)
        if len(parts) == 1:
            continue
        name = asset["name"]
        ps_name = name.replace("'", "''")
        sh_name = "'" + name.replace("'", "'\"'\"'") + "'"
        lines += [f"## {name}", "", f"所需分卷：`{parts[0][0]}` 至 `{parts[-1][0]}`。", "",
                  "Windows PowerShell（在下载目录执行）：", "", "```powershell",
                  f"$name = '{ps_name}'", f"$count = {len(parts)}",
                  "$parts = 1..$count | ForEach-Object { '{0}.{1:D3}' -f $name, $_ }",
                  "$parts | ForEach-Object { if (!(Test-Path -LiteralPath $_)) { throw \"缺少分卷：$_\" } }",
                  "$output = [System.IO.File]::Open((Join-Path $PWD $name), [System.IO.FileMode]::Create)",
                  "try {", "    foreach ($part in $parts) {",
                  "        $inputFile = [System.IO.File]::OpenRead((Join-Path $PWD $part))",
                  "        try { $inputFile.CopyTo($output) } finally { $inputFile.Dispose() }",
                  "    }", "} finally { $output.Dispose() }",
                  "Get-FileHash -Algorithm SHA256 -LiteralPath $name", "```", "",
                  "macOS / Linux：", "", "```sh",
                  "cat " + " ".join(sh_name + f".{index + 1:03}" for index in range(len(parts)))
                  + " > " + sh_name,
                  "shasum -a 256 " + sh_name, "```", ""]
        if asset.get("digest"):
            lines += [f"原始文件 SHA-256：`{asset['digest'].removeprefix('sha256:')}`", ""]
    lines += ["所有原始文件与分卷的校验值见同一 Release 中的 `SHA256SUMS-Gitee.txt`。", "",
              f"GitHub 原始完整包：{release['html_url']}", ""]
    return "\n".join(lines)


def release_body(release, complete=False):
    body = release["body"] or ""
    if any(len(asset_parts(asset)) > 1 for asset in release["assets"]):
        body += ("\n\n---\n### Gitee 下载说明\n\n"
                 "Gitee 单附件上限为 100 MB，安装包已按 95 MB 分卷。"
                 "请下载同名的全部 `.001`、`.002` 等分卷，按照附件 "
                 "`GITEE_DOWNLOAD.md` 合并，再用 `SHA256SUMS-Gitee.txt` 校验并解压。\n\n"
                 f"也可下载 [GitHub 原始完整包]({release['html_url']})。\n")
    if complete:
        body += f"\n\n{MARKER}{fingerprint(release)} -->\n"
    return body


def retained_tags(releases):
    """Keep the newest published stable release and newest prerelease."""
    tags = set()
    for prerelease in (False, True):
        candidates = [release for release in releases if release["prerelease"] == prerelease]
        if candidates:
            latest = max(candidates, key=lambda release: release["published_at"])
            tags.add(latest["tag_name"])
    return tags


def archived_body(release):
    body = release["body"] or ""
    body += ("\n\n---\n### 历史安装包下载\n\n"
             "Gitee 仓库附件总配额为 1 GB，因此仅保留最新正式版和最新预览版的镜像附件。"
             "本版本的原始安装包保留在 GitHub：\n\n")
    for asset in release["assets"]:
        body += f"- [{asset['name']}]({asset['browser_download_url']})\n"
    body += f"\n[查看 GitHub 原始 Release]({release['html_url']})\n"
    return body


def restore_latest_stable(mirror, releases):
    """Gitee's latest endpoint uses update time, including historical edits."""
    stable = [release for release in releases if not release["prerelease"]]
    if not stable:
        return
    latest = max(stable, key=lambda release: release["published_at"])
    current = mirror.api("GET", "/releases/latest")
    if current["tag_name"] == latest["tag_name"]:
        return
    target = mirror.api("GET", "/releases/tags/" + quote(latest["tag_name"], safe=""))
    body = re.sub(r"\n*<!-- gitee-sync-latest-check: .*? -->\n*", "", target["body"])
    body += f"\n\n<!-- gitee-sync-latest-check: {datetime.now(timezone.utc).isoformat()} -->\n"
    mirror.api("PATCH", f"/releases/{target['id']}", json={
        "tag_name": target["tag_name"], "name": target["name"], "body": body,
        "prerelease": target["prerelease"]})
    if mirror.api("GET", "/releases/latest")["tag_name"] != latest["tag_name"]:
        raise RuntimeError("Gitee latest release did not resolve to the newest stable version")
    print(f"LATEST STABLE {latest['tag_name']}", flush=True)


class Mirror:
    def __init__(self, github_repo, gitee_repo, cache):
        import requests

        self.http = requests
        self.github_repo = github_repo
        self.api_url = f"https://gitee.com/api/v5/repos/{gitee_repo}"
        self.token = os.environ["GITEE_TOKEN"].strip()
        self.headers = {"Authorization": "Bearer " + self.token}
        self.cache = cache

    def api(self, method, path, **kwargs):
        for attempt in range(3):
            response = self.http.request(method, self.api_url + path, headers=self.headers,
                                        timeout=(30, 120), **kwargs)
            if response.ok:
                return response.json() if response.content else None
            if method == "GET" and (response.status_code == 429 or response.status_code >= 500) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"Gitee {method} {path}: HTTP {response.status_code}: "
                               + response.text[:600].replace(self.token, "[redacted]"))

    def list_all(self, path):
        items = []
        page = 1
        while True:
            batch = self.api("GET", f"{path}?per_page=100&page={page}")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    def attachments(self, release_id):
        return self.list_all(f"/releases/{release_id}/attach_files")

    def upload(self, release_id, path, existing):
        name, size = path.name, path.stat().st_size
        match = next((item for item in existing if item["name"] == name), None)
        if match:
            if match["size"] != size:
                raise RuntimeError(f"Refusing to overwrite a different existing attachment: {name}")
            return match
        for attempt in range(3):
            print(f"UPLOAD {name} ({size / 1_000_000:.1f} MB)", flush=True)
            with path.open("rb") as source:
                response = self.http.post(
                    self.api_url + f"/releases/{release_id}/attach_files", headers=self.headers,
                    files={"file": (name, source, "application/octet-stream")}, timeout=(30, 900))
            if response.ok:
                item = response.json()
                if item.get("name") != name or item.get("size") != size:
                    raise RuntimeError(f"Upload returned unexpected metadata: {name}")
                print(f"UPLOADED {name}", flush=True)
                return item
            # Before retrying a response from a gateway, check whether the write succeeded.
            if response.status_code == 429 or response.status_code >= 500:
                match = next((item for item in self.attachments(release_id)
                              if item["name"] == name and item["size"] == size), None)
                if match:
                    return match
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
            raise RuntimeError(f"Upload {name}: HTTP {response.status_code}: "
                               + response.text[:600].replace(self.token, "[redacted]"))

    def download(self, release, asset, directory):
        path = directory / safe_name(asset["name"])
        digest = asset.get("digest")
        if not (path.exists() and path.stat().st_size == asset["size"]
                and (not digest or "sha256:" + checksum(path) == digest)):
            print(f"DOWNLOAD {release['tag_name']} / {asset['name']}", flush=True)
            subprocess.run(["gh", "release", "download", release["tag_name"],
                            "--repo", self.github_repo, "--pattern", asset["name"],
                            "--dir", str(directory), "--clobber"], check=True)
        actual = checksum(path)
        if path.stat().st_size != asset["size"] or (digest and digest != "sha256:" + actual):
            raise RuntimeError(f"Downloaded file failed size/SHA-256 verification: {path.name}")
        return path, actual

    def archive(self, release, target):
        # Delete only files belonging to this mirror, leaving unrelated uploads.
        owned = {name for asset in release["assets"] for name, _ in asset_parts(asset)}
        owned.update(asset["name"] for asset in release["assets"])
        owned.update(("GITEE_DOWNLOAD.md", "SHA256SUMS-Gitee.txt"))
        removed = 0
        for item in self.attachments(target["id"]):
            if item["name"] in owned:
                self.api("DELETE", f"/releases/{target['id']}/attach_files/{item['id']}")
                removed += 1
                print(f"REMOVED OLD MIRROR {release['tag_name']}/{item['name']}", flush=True)
        fields = {"tag_name": release["tag_name"], "name": release["name"] or release["tag_name"],
                  "body": archived_body(release), "prerelease": release["prerelease"]}
        if any(target.get(key) != value for key, value in fields.items()):
            self.api("PATCH", f"/releases/{target['id']}", json=fields)
        print(f"ARCHIVED RELEASE {release['tag_name']}: GitHub download links retained", flush=True)
        return {"tag": release["tag_name"], "id": target["id"], "mode": "github-links",
                "removed_files": removed, "verified": True}

    def sync(self, release, target):
        tag = safe_name(release["tag_name"])
        existing = self.attachments(target["id"])
        expected = [part for asset in release["assets"] for part in asset_parts(asset)]
        files = {item["name"]: item["size"] for item in existing}
        marker = f"{MARKER}{fingerprint(release)} -->"
        already_complete = (marker in target["body"]
                            and all(files.get(name) == size for name, size in expected)
                            and "SHA256SUMS-Gitee.txt" in files and "GITEE_DOWNLOAD.md" in files)
        if MARKER in target["body"] and marker not in target["body"]:
            raise RuntimeError(f"Source attachments changed for {tag}; review existing Gitee files before replacing them")
        if not already_complete:
            directory = self.cache / tag
            directory.mkdir(parents=True, exist_ok=True)
            hashes = []
            for asset in release["assets"]:
                path, digest = self.download(release, asset, directory)
                hashes.append(f"{digest}  {path.name}")
                for part in split_asset(path):
                    if part != path:
                        hashes.append(f"{checksum(part)}  {part.name}")
                    self.upload(target["id"], part, existing)
            notes = directory / "GITEE_DOWNLOAD.md"
            notes.write_text(download_notes(release), encoding="utf-8", newline="\n")
            sums = directory / "SHA256SUMS-Gitee.txt"
            sums.write_text("\n".join(hashes) + "\n", encoding="utf-8", newline="\n")
            self.upload(target["id"], notes, existing)
            self.upload(target["id"], sums, existing)
            remote_files = {item["name"]: item["size"] for item in self.attachments(target["id"])}
            for name, size in expected + [(notes.name, notes.stat().st_size), (sums.name, sums.stat().st_size)]:
                if remote_files.get(name) != size:
                    raise RuntimeError(f"Gitee attachment verification failed: {tag}/{name}")
        fields = {"tag_name": tag, "name": release["name"] or tag,
                  "body": release_body(release, complete=True), "prerelease": release["prerelease"]}
        if any(target.get(key) != value for key, value in fields.items()):
            self.api("PATCH", f"/releases/{target['id']}", json=fields)
        print(f"VERIFIED RELEASE {tag}: {len(expected)} mirrored files", flush=True)
        return {"tag": tag, "id": target["id"], "mode": "mirrored",
                "files": len(expected), "verified": True}


def github_releases(repository):
    result = subprocess.run(["gh", "api", f"repos/{repository}/releases?per_page=100", "--paginate", "--slurp"],
                            check=True, capture_output=True, encoding="utf-8")
    return [release for page in json.loads(result.stdout) for release in page if not release["draft"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-repo", default="Tortes/MaaRoco")
    parser.add_argument("--gitee-repo", default="tortes/maa-roco")
    parser.add_argument("--tag", help="Only upload assets for this tag; still archive other historical releases")
    parser.add_argument("--all-assets", action="store_true",
                        help="Mirror every release's assets without pruning; requires sufficient Gitee quota")
    parser.add_argument("--cache-dir", type=Path, default=Path(tempfile.gettempdir()) / "maaroco-gitee")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    mirror = Mirror(args.github_repo, args.gitee_repo, args.cache_dir)
    releases = github_releases(args.github_repo)
    keep = {release["tag_name"] for release in releases} if args.all_assets else retained_tags(releases)
    if args.tag and not any(release["tag_name"] == args.tag for release in releases):
        raise RuntimeError(f"No published GitHub release for tag {args.tag}")
    existing = {item["tag_name"]: item for item in mirror.list_all("/releases")}
    targets = {}
    for release in sorted(releases, key=lambda item: item["published_at"]):
        tag = safe_name(release["tag_name"])
        target = existing.get(tag)
        if target is None:
            # Gitee requires a branch or commit SHA for target_commitish. Peel
            # annotated tags so a release never accidentally targets main.
            commit = subprocess.check_output(
                ["git", "-C", str(Path(__file__).resolve().parent.parent), "rev-parse",
                 "--verify", f"refs/tags/{tag}^{{commit}}"], text=True).strip()
            target = mirror.api("POST", "/releases", json={
                "tag_name": tag, "target_commitish": commit, "name": release["name"] or tag,
                "body": release_body(release), "prerelease": release["prerelease"]})
        targets[tag] = target
    report = {"releases": [], "errors": []}
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.cache_dir / "sync-report.json"
    # Free the space used by old versions before uploading their replacements.
    for release in sorted(releases, key=lambda item: item["published_at"]):
        if release["tag_name"] not in keep:
            report["releases"].append(mirror.archive(release, targets[release["tag_name"]]))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {executor.submit(mirror.sync, release, targets[release["tag_name"]]): release["tag_name"]
                for release in releases if release["tag_name"] in keep
                and (not args.tag or release["tag_name"] == args.tag)}
        while jobs:
            done, _ = concurrent.futures.wait(jobs, timeout=30, return_when=concurrent.futures.FIRST_COMPLETED)
            if not done:
                print(f"PROGRESS {len(report['releases'])}/{len(releases)} releases verified; "
                      f"{len(report['errors'])} errors", flush=True)
            for job in done:
                tag = jobs.pop(job)
                try:
                    report["releases"].append(job.result())
                except Exception as error:
                    message = str(error).replace(mirror.token, "[redacted]")
                    report["errors"].append({"tag": tag, "message": message})
                    print(f"ERROR {tag}: {message}", flush=True)
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["errors"]:
        raise SystemExit(f"{len(report['errors'])} releases failed; see {report_path}")
    restore_latest_stable(mirror, releases)
    print(f"Verified {len(report['releases'])} releases. Report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
