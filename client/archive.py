import re
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path


class ArchiveError(RuntimeError):
    """Base exception for package extraction failures."""


class UnsafeArchiveError(ArchiveError):
    """An archive member could escape the selected destination."""


class UnsupportedArchiveError(ArchiveError):
    """The downloaded package format is not supported."""


def _destination_path(target_dir: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise UnsafeArchiveError("Archive contains an absolute path")

    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise UnsafeArchiveError("Archive contains an unsafe relative path")

    root = target_dir.resolve()
    destination = root.joinpath(*parts).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise UnsafeArchiveError("Archive member escapes the destination") from exc
    return destination


def _extract_zip(package_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(package_path, "r") as archive:
        for member in archive.infolist():
            destination = _destination_path(target_dir, member.filename)
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise UnsafeArchiveError("ZIP symbolic links are not allowed")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _extract_tar_stream(archive: tarfile.TarFile, target_dir: Path) -> None:
    for member in archive:
        destination = _destination_path(target_dir, member.name)
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if not member.isreg():
            raise UnsafeArchiveError("TAR links and special files are not allowed")
        source = archive.extractfile(member)
        if source is None:
            raise ArchiveError("TAR member cannot be read")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


def _extract_tar(package_path: Path, target_dir: Path) -> None:
    with tarfile.open(package_path, mode="r:*") as archive:
        _extract_tar_stream(archive, target_dir)


def _extract_tar_zst(package_path: Path, target_dir: Path) -> None:
    import zstandard as zstd

    with package_path.open("rb") as source:
        decompressor = zstd.ZstdDecompressor()
        with decompressor.stream_reader(source) as reader, tarfile.open(
            fileobj=reader, mode="r|"
        ) as archive:
            _extract_tar_stream(archive, target_dir)


def _iso_name(value: str | bytes) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return re.sub(r";\d+$", "", value)


def _iso_source_name(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _extract_iso(package_path: Path, target_dir: Path) -> None:
    import pycdlib

    iso = pycdlib.PyCdlib()
    iso.open(str(package_path))
    try:
        for parent, directories, files in iso.walk(iso_path="/"):
            parent_name = _iso_name(parent).lstrip("/")
            for directory in directories:
                destination = _destination_path(
                    target_dir,
                    "/".join(part for part in (parent_name, _iso_name(directory)) if part),
                )
                destination.mkdir(parents=True, exist_ok=True)
            for filename in files:
                source_name = "/".join(
                    part
                    for part in (
                        _iso_source_name(parent).lstrip("/"),
                        _iso_source_name(filename),
                    )
                    if part
                )
                destination_name = "/".join(
                    part for part in (parent_name, _iso_name(filename)) if part
                )
                destination = _destination_path(target_dir, destination_name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    iso.get_file_from_iso_fp(iso_path=f"/{source_name}", outfp=output)
    finally:
        iso.close()


def extract_package(package_path: Path, target_dir: Path) -> None:
    """Extract a supported package without trusting archive member paths."""
    package_path = package_path.resolve(strict=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = "".join(package_path.suffixes).lower()

    try:
        if suffix.endswith(".tar.zst"):
            _extract_tar_zst(package_path, target_dir)
        elif suffix.endswith(".zip"):
            _extract_zip(package_path, target_dir)
        elif suffix.endswith(".iso"):
            _extract_iso(package_path, target_dir)
        elif suffix.endswith((".tar", ".tgz", ".tar.gz")):
            _extract_tar(package_path, target_dir)
        else:
            raise UnsupportedArchiveError(f"Unsupported package type: {package_path.name}")
    except ArchiveError:
        raise
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ArchiveError("Package extraction failed") from exc
