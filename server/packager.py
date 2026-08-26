import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import zstandard as zstd
from fastapi.responses import FileResponse

from .config import CACHE_DIR, DICOM_ROOT


class PackageBuildError(RuntimeError):
    """A study package cannot be built safely from the indexed files."""


@dataclass(frozen=True)
class StudyFile:
    series_uid: str
    sop_uid: str
    path: str


@dataclass(frozen=True)
class _PreparedFile:
    record: StudyFile
    source: Path
    archive_path: str
    size: int
    mtime_ns: int


def _safe_uid_component(value: str, prefix: str) -> str:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value or ""):
        return value
    digest = hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _prepare_files(
    study_uid: str,
    files: Iterable[StudyFile],
    storage_root: Path,
) -> list[_PreparedFile]:
    try:
        root = storage_root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise PackageBuildError("Configured DICOM_ROOT is unavailable") from exc

    study_component = _safe_uid_component(study_uid, "study")
    prepared: list[_PreparedFile] = []
    archive_paths: set[str] = set()

    for record in files:
        try:
            source = Path(record.path).expanduser().resolve(strict=True)
            source.relative_to(root)
        except (OSError, ValueError) as exc:
            raise PackageBuildError(
                "An indexed study file is missing or outside DICOM_ROOT"
            ) from exc
        if not source.is_file():
            raise PackageBuildError("An indexed study entry is not a regular file")

        series_component = _safe_uid_component(record.series_uid, "series")
        sop_component = _safe_uid_component(record.sop_uid, "instance")
        archive_path = f"{study_component}/{series_component}/{sop_component}.dcm"
        if archive_path in archive_paths:
            raise PackageBuildError("Duplicate DICOM instance in study index")
        archive_paths.add(archive_path)

        stat = source.stat()
        prepared.append(
            _PreparedFile(
                record=record,
                source=source,
                archive_path=archive_path,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )

    prepared.sort(key=lambda item: item.archive_path)
    return prepared


def _fingerprint(study_uid: str, files: Iterable[_PreparedFile]) -> str:
    digest = hashlib.sha256()
    digest.update(study_uid.encode("utf-8"))
    for item in files:
        digest.update(b"\0")
        digest.update(item.record.series_uid.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.record.sop_uid.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item.mtime_ns).encode("ascii"))
    return digest.hexdigest()


def _write_tar_zst(
    package_path: Path,
    study_uid: str,
    prepared: list[_PreparedFile],
    fingerprint: str,
) -> str:
    package_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 2,
        "study_uid": study_uid,
        "fingerprint": fingerprint,
        "generated": int(time.time()),
        "files": [
            {
                "path": item.archive_path,
                "series_uid": item.record.series_uid,
                "sop_uid": item.record.sop_uid,
                "size": item.size,
                "mtime_ns": item.mtime_ns,
            }
            for item in prepared
        ],
    }

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=package_path.parent,
            prefix=f".{package_path.name}.",
            suffix=".partial",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            compressor = zstd.ZstdCompressor(level=6)
            with compressor.stream_writer(
                temporary, closefd=False
            ) as compressed, tarfile.open(fileobj=compressed, mode="w|") as archive:
                for item in prepared:
                    archive.add(
                        item.source,
                        arcname=item.archive_path,
                        recursive=False,
                    )
                manifest_data = json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
                info = tarfile.TarInfo(name="manifest.json")
                info.size = len(manifest_data)
                info.mtime = manifest["generated"]
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(manifest_data))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, package_path)
    except (OSError, tarfile.TarError, zstd.ZstdError) as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise PackageBuildError("Failed to build study package") from exc
    return fingerprint


def build_tar_zst(
    package_path: Path,
    study_uid: str,
    files: Iterable[StudyFile],
    storage_root: Path,
) -> str:
    """Build an atomic package and return its content fingerprint."""
    prepared = _prepare_files(study_uid, files, storage_root)
    if not prepared:
        raise PackageBuildError("Study has no files to package")
    fingerprint = _fingerprint(study_uid, prepared)
    return _write_tar_zst(package_path, study_uid, prepared, fingerprint)


def get_or_build_package(
    study_uid: str,
    file_list: Iterable[StudyFile],
) -> FileResponse:
    files = list(file_list)
    prepared = _prepare_files(study_uid, files, Path(DICOM_ROOT))
    if not prepared:
        raise PackageBuildError("Study has no files to package")

    fingerprint = _fingerprint(study_uid, prepared)
    study_key = hashlib.sha256(study_uid.encode("utf-8")).hexdigest()[:20]
    package_path = Path(CACHE_DIR) / f"{study_key}-{fingerprint[:20]}.tar.zst"
    if not package_path.exists():
        _write_tar_zst(package_path, study_uid, prepared, fingerprint)

    download_name = f"{_safe_uid_component(study_uid, 'study')}.tar.zst"
    return FileResponse(
        str(package_path),
        media_type="application/zstd",
        filename=download_name,
        headers={
            "Accept-Ranges": "bytes",
            "X-Package-Fingerprint": fingerprint,
        },
    )
