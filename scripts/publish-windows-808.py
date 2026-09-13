#!/usr/bin/env python3
"""Promote exactly the Windows artifacts that passed the complete CI workflow.

No rebuilding, no overwriting existing release assets, and no bootstrap through
8.0.7's unsafe update channel. Invoked by an explicit main release request.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    result = subprocess.run(args, cwd=REPO, check=True, capture_output=True, text=True, encoding="utf-8")
    if result.stderr:
        print(result.stderr, end="", flush=True)
    return result.stdout


def api(path: str) -> dict:
    return json.loads(command("gh", "api", path))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def unique(root: Path, name: str) -> Path:
    found = list(root.rglob(name))
    require(len(found) == 1 and found[0].is_file(), f"Expected one validated artifact: {name}")
    return found[0]


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    require(repository == "jaroslavkucacz-code/TURTO-ZakazkyApp", "Unexpected repository")
    request = read(REPO / "windows_release_request.json")
    version = str(request.get("version", ""))
    source_commit = str(request.get("source_commit", ""))
    run_id = str(request.get("validated_run_id", ""))
    require(request.get("channel") == "windows", "Wrong release channel")
    require(re.fullmatch(r"\d+\.\d+\.\d+", version) is not None, "Stable x.y.z version required")
    require(version == (REPO / "build/windows/version.txt").read_text(encoding="utf-8-sig").strip(), "Version mismatch")
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None and run_id.isdigit(), "Validated run and exact source commit required")
    require(not request.get("bridge_legacy_preview"), "Do not bootstrap through the unsafe old updater")
    notes = str(request.get("notes", "")).strip()
    require(bool(notes), "Release notes required")
    command("git", "merge-base", "--is-ancestor", source_commit, "HEAD")
    allowed = {"windows_release_request.json", "UPDATER_8.0.8_STATUS.md", "latest-windows-v2.json"}
    changed = set(command("git", "diff", "--name-only", source_commit, "HEAD").splitlines())
    require(changed <= allowed, "Application/build sources changed since validation: " + repr(sorted(changed - allowed)))
    legacy = REPO / "latest-windows.json"
    legacy_hash = digest(legacy)
    require(read(legacy).get("version") == "8.0.7", "Legacy channel must stay at 8.0.7")

    run = api(f"repos/{repository}/actions/runs/{run_id}")
    require(run.get("conclusion") == "success" and run.get("status") == "completed", "Validation run has not passed")
    require(run.get("head_sha") == source_commit, "CI validated a different source commit")
    require(run.get("path") == ".github/workflows/validate-800-windows-installer.yml", "Wrong validation workflow")
    require(run.get("event") == "push", "Only a complete branch push validation may be promoted")
    require(run.get("head_repository", {}).get("full_name") == repository, "Artifact source repository mismatch")
    jobs = api(f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100").get("jobs", [])
    by_name = {job["name"]: job for job in jobs}
    for name in ("source-linux", "build-windows-preview", "clean-install-smoke"):
        require(by_name.get(name, {}).get("conclusion") == "success", f"Required validation did not pass: {name}")

    with tempfile.TemporaryDirectory(prefix="turto-validated-release-") as td:
        stage = Path(td)
        packages, reports = stage / "packages", stage / "reports"
        command("gh", "run", "download", run_id, "--repo", repository, "--name", "TURTO-CRM-8.0-Windows-preview", "--dir", str(packages))
        command("gh", "run", "download", run_id, "--repo", repository, "--name", "TURTO-CRM-808-smoke-report", "--dir", str(reports))
        manifest = read(unique(packages, "latest-windows.preview.json"))
        report_path = unique(reports, "808-smoke-report.json")
        report = read(report_path)
        setup_name, package_name = f"TURTO_CRM_Setup_{version}.exe", f"TURTO_CRM_Update_{version}.zip"
        setup, package = unique(packages, setup_name), unique(packages, package_name)
        setup_sha, package_sha = digest(setup), digest(package)
        require(manifest.get("version") == version and manifest.get("source_commit") == source_commit, "Build manifest mismatch")
        require(manifest.get("installer") == setup_name and manifest.get("package") == package_name, "Build filenames mismatch")
        require(manifest.get("installer_sha256") == setup_sha and manifest.get("sha256") == package_sha, "Build artifact SHA-256 mismatch")
        require(report.get("ok") is True and report.get("version") == version and report.get("source_commit") == source_commit, "Frozen smoke report mismatch")
        require(report.get("installer_sha256") == setup_sha and report.get("package_sha256") == package_sha, "Smoke test exercised different binaries")
        require(len(report.get("checks", [])) >= 10, "Incomplete frozen smoke coverage")
        published_report = stage / f"TURTO_CRM_{version}_validation.json"
        shutil.copyfile(report_path, published_report)
        sums = stage / "SHA256SUMS.txt"
        sums.write_text(f"{setup_sha}  {setup_name}\n{package_sha}  {package_name}\n{digest(published_report)}  {published_report.name}\n", encoding="utf-8")
        notes_path = stage / "release-notes.md"
        notes_path.write_text(f"# TURTO CRM {version}\n\n{notes}\n\n## Ověření vydání\n\nPublikovány jsou přesně soubory z úspěšného Windows sestavení a integračních testů, bez nového překladu po testování.\n\n- Zdrojový commit: `{source_commit}`\n- Kontrola: https://github.com/{repository}/actions/runs/{run_id}\n- Testovací protokol: `{published_report.name}`\n- Databáze ani uživatelská data nejsou součástí instalačního balíčku.\n- ESET na hostovaném testovacím stroji není; tato verze není prohlášena za ověřenou ESETem.\n", encoding="utf-8")
        tag = "v" + version
        existing = subprocess.run(["gh", "api", f"repos/{repository}/releases/tags/{tag}"], capture_output=True, text=True, encoding="utf-8", cwd=REPO)
        if existing.returncode:
            require("HTTP 404" in existing.stderr, "Cannot verify existing release: " + existing.stderr)
            print(command("gh", "release", "create", tag, str(setup), str(package), str(published_report), str(sums), "--repo", repository, "--target", source_commit, "--title", "TURTO CRM " + version, "--notes-file", str(notes_path), "--latest"), flush=True)
        release = api(f"repos/{repository}/releases/tags/{tag}")
        require(not release.get("draft") and not release.get("prerelease"), "Release is not public stable")
        ref = api(f"repos/{repository}/git/ref/tags/{tag}")["object"]
        if ref.get("type") == "tag":
            ref = api(f"repos/{repository}/git/tags/{ref['sha']}")["object"]
        require(ref.get("sha") == source_commit and ref.get("type") == "commit", "Release tag is not the validated commit")
        assets = {asset["name"]: asset for asset in release.get("assets", [])}
        for file in (setup, package, published_report, sums):
            asset = assets.get(file.name, {})
            require(asset.get("state") == "uploaded" and asset.get("digest") == "sha256:" + digest(file), "Published asset differs from validated bytes: " + file.name)
        release_root = f"https://github.com/{repository}/releases/download/{tag}"
        safe_manifest = {"format": "turto-crm-windows-update-v1", "channel": "windows", "version": version, "package": package_name, "sha256": package_sha, "download_url": release_root + "/" + package_name, "installer": setup_name, "installer_sha256": setup_sha, "installer_url": release_root + "/" + setup_name, "source_commit": source_commit, "validated_run_id": int(run_id), "updater_format": "onedir-v1", "minimum_safe_updater": "8.0.8"}
        command("git", "config", "user.name", "TURTO Release Bot")
        command("git", "config", "user.email", "actions@users.noreply.github.com")
        command("git", "pull", "--rebase", "origin", "main")
        require(digest(legacy) == legacy_hash, "Legacy manifest changed during publication; stopping safe-channel publication")
        safe_path = REPO / "latest-windows-v2.json"
        safe_path.write_text(json.dumps(safe_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        command("git", "add", "latest-windows-v2.json")
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode:
            print(command("git", "commit", "-m", "Publish verified TURTO CRM Windows " + version + " safe update channel"), flush=True)
            print(command("git", "push", "origin", "HEAD:main"), flush=True)
        require(digest(legacy) == legacy_hash, "Old update channel changed")
        print(json.dumps({"released": version, "source_commit": source_commit, "validation_run": run_id, "release_url": release["html_url"], "installer_sha256": setup_sha, "package_sha256": package_sha, "legacy_channel": "8.0.7", "safe_manifest": "latest-windows-v2.json"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
