from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict
from zipfile import ZipFile

from app_builder.release_preflight import (
    PublicationPreflightResult,
    run_publication_preflight,
    write_checksums_file,
    write_release_notes,
)


class ReleaseFixture(TypedDict):
    payload: Path
    installer: Path
    manifest: Path
    checksums: Path
    notes: Path
    artifacts: tuple[Path, ...]


class TestPublicationPreflight(unittest.TestCase):
    def test_accepts_clean_release_with_verified_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)

            result = run_publication_preflight(
                project_root,
                version="1.0.0",
                app_name="Demo",
                dist_dir=project_root / "dist",
                artifacts=release["artifacts"],
                payload_archive=release["payload"],
                installer_archive=release["installer"],
                manifest_path=release["manifest"],
                checksums_path=release["checksums"],
                release_notes_path=release["notes"],
            )

            self.assertEqual(
                _git(project_root, "rev-parse", "HEAD"), result.head_commit
            )
            self.assertTrue(result.origin_url)

    def test_accepts_selected_extra_output_with_complete_checksums(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)
            extra = project_root / "dist" / "tools" / "demo-tools.exe"
            extra.parent.mkdir()
            extra.write_bytes(b"tools")
            release_outputs = (
                release["payload"],
                release["installer"],
                release["manifest"],
                extra,
                release["checksums"],
            )
            write_checksums_file(
                (
                    release["payload"],
                    release["installer"],
                    release["manifest"],
                    extra,
                ),
                release["checksums"],
            )
            publication = (
                release["installer"],
                release["manifest"],
                extra,
                release["checksums"],
            )
            write_release_notes(
                project_root,
                app_name="Demo",
                version="1.0.0",
                artifacts=publication,
                output_path=release["notes"],
            )

            run_publication_preflight(
                project_root,
                version="1.0.0",
                app_name="Demo",
                dist_dir=project_root / "dist",
                artifacts=publication,
                release_outputs=release_outputs,
                payload_archive=release["payload"],
                installer_archive=release["installer"],
                manifest_path=release["manifest"],
                checksums_path=release["checksums"],
                release_notes_path=release["notes"],
            )

    def test_rejects_dirty_source_outside_dist(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)
            (project_root / "untracked.txt").write_text("dirty", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "worktree is not clean"):
                _run_preflight(project_root, release)

    def test_rejects_local_tag_that_points_to_another_commit(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, remote = _create_repository(Path(temp_dir_str))
            _run(project_root, "git", "tag", "1.0.0")
            _run(project_root, "git", "push", str(remote), "refs/tags/1.0.0")
            (project_root / "tracked.txt").write_text("second", encoding="utf-8")
            _run(project_root, "git", "add", "tracked.txt")
            _run(project_root, "git", "commit", "-m", "Second commit")
            release = _write_release(project_root)

            with self.assertRaisesRegex(RuntimeError, "local tag.*not HEAD"):
                _run_preflight(project_root, release)

    def test_rejects_app_builder_package_version_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(
                Path(temp_dir_str),
                pyproject='[project]\nname = "app-builder"\nversion = "1.2.0"\n',
            )
            release = _write_release(
                project_root, app_name="app-builder", version="1.3.0"
            )

            with self.assertRaisesRegex(
                RuntimeError, "package version.*does not match"
            ):
                _run_preflight(
                    project_root,
                    release,
                    app_name="app-builder",
                    version="1.3.0",
                )

    def test_rejects_tampered_artifact(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)
            release["manifest"].write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "manifest identity"):
                _run_preflight(project_root, release)

    def test_rejects_extra_checksum_entry(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)
            with release["checksums"].open("a", encoding="ascii") as checksum_file:
                checksum_file.write(f"{'0' * 64}  unexpected.bin\n")

            with self.assertRaisesRegex(RuntimeError, "checksum inventory"):
                _run_preflight(project_root, release)

    def test_allows_another_version_in_dist(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)
            (project_root / "dist" / "demo-1.0.0-rc1-installer.exe").write_bytes(
                b"another release"
            )

            _run_preflight(project_root, release)

    def test_rejects_payload_that_differs_from_installer_entry(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)
            release["payload"].write_bytes(release["payload"].read_bytes() + b"changed")
            write_checksums_file(
                (release["payload"], release["installer"], release["manifest"]),
                release["checksums"],
            )

            with self.assertRaisesRegex(RuntimeError, "embedded payload differs"):
                _run_preflight(project_root, release)

    def test_rejects_embedded_manifest_that_differs_from_published_file(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root, _ = _create_repository(Path(temp_dir_str))
            release = _write_release(project_root)
            _replace_installer_script(
                release["installer"], "$EmbeddedManifestJson = @'\n{}\n'@\n"
            )
            write_checksums_file(
                (release["payload"], release["installer"], release["manifest"]),
                release["checksums"],
            )

            with self.assertRaisesRegex(RuntimeError, "embedded manifest differs"):
                _run_preflight(project_root, release)


def _create_repository(
    root: Path, *, pyproject: str | None = None
) -> tuple[Path, Path]:
    project_root = root / "project"
    remote = root / "remote.git"
    project_root.mkdir()
    _run(root, "git", "init", "--bare", str(remote))
    _run(project_root, "git", "init")
    _run(project_root, "git", "config", "user.email", "audit@example.invalid")
    _run(project_root, "git", "config", "user.name", "app-builder tests")
    _run(project_root, "git", "remote", "add", "origin", str(remote))
    (project_root / ".gitignore").write_text("dist/\n", encoding="utf-8")
    (project_root / "tracked.txt").write_text("first", encoding="utf-8")
    if pyproject is not None:
        (project_root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    _run(project_root, "git", "add", ".")
    _run(project_root, "git", "commit", "-m", "Initial commit")
    _run(project_root, "git", "push", "-u", "origin", "HEAD")
    return project_root, remote


def _write_release(
    project_root: Path, *, app_name: str = "Demo", version: str = "1.0.0"
) -> ReleaseFixture:
    dist = project_root / "dist"
    dist.mkdir(exist_ok=True)
    prefix = f"{app_name.lower().replace(' ', '-')}-{version}"
    payload = dist / f"{prefix}.zip"
    installer = dist / f"{prefix}-installer.exe"
    manifest = dist / f"{prefix}-manifest.json"
    checksums = dist / f"{prefix}-SHA256SUMS.txt"
    notes = dist / f"{prefix}-release-notes.md"
    with ZipFile(payload, "w") as payload_zip:
        payload_zip.writestr("app.txt", "app")
    manifest_payload = {
        "name": app_name,
        "version": version,
        "payload_archive": payload.name,
    }
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    with ZipFile(installer, "w") as installer_zip:
        installer_zip.writestr("install.cmd", "@echo off\n")
        installer_zip.writestr(
            "bin/install.ps1",
            "$EmbeddedManifestJson = @'\n"
            + json.dumps(manifest_payload)
            + "\n'@\nexit 0\n",
        )
        installer_zip.write(payload, payload.name)
    artifacts = (payload, installer, manifest, checksums)
    write_checksums_file((payload, installer, manifest), checksums)
    write_release_notes(
        project_root,
        app_name=app_name,
        version=version,
        artifacts=artifacts,
        output_path=notes,
    )
    return {
        "payload": payload,
        "installer": installer,
        "manifest": manifest,
        "checksums": checksums,
        "notes": notes,
        "artifacts": artifacts,
    }


def _run_preflight(
    project_root: Path,
    release: ReleaseFixture,
    *,
    app_name: str = "Demo",
    version: str = "1.0.0",
) -> PublicationPreflightResult:
    return run_publication_preflight(
        project_root,
        version=version,
        app_name=app_name,
        dist_dir=project_root / "dist",
        artifacts=release["artifacts"],
        payload_archive=release["payload"],
        installer_archive=release["installer"],
        manifest_path=release["manifest"],
        checksums_path=release["checksums"],
        release_notes_path=release["notes"],
    )


def _replace_installer_script(installer: Path, script: str) -> None:
    replacement = installer.with_suffix(".replacement.zip")
    with ZipFile(installer) as source_zip, ZipFile(replacement, "w") as target_zip:
        for item in source_zip.infolist():
            if item.filename != "bin/install.ps1":
                target_zip.writestr(item, source_zip.read(item.filename))
        target_zip.writestr("bin/install.ps1", script)
    replacement.replace(installer)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
