import asyncio
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from client.archive import UnsafeArchiveError, extract_package
from client.files import safe_download_filename
from server import packager
from server.packager import PackageBuildError, StudyFile, build_tar_zst


class PackageFlowTests(unittest.TestCase):
    def test_download_filename_cannot_escape_download_directory(self):
        self.assertEqual(safe_download_filename("../../study.tar.zst"), "study.tar.zst")
        self.assertEqual(safe_download_filename(r"C:\\temp\\study.zip"), "study.zip")
        self.assertEqual(safe_download_filename("CON.zip"), "_CON.zip")
        self.assertEqual(safe_download_filename("", "../../fallback.pkg"), "fallback.pkg")

    def test_package_preserves_two_series_with_same_source_filename(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "storage"
            first = root / "source-a" / "IMG_00001.dcm"
            second = root / "source-b" / "IMG_00001.dcm"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"first-series")
            second.write_bytes(b"second-series")
            package = Path(temporary_dir) / "study.tar.zst"

            fingerprint = build_tar_zst(
                package,
                "1.2.3",
                [
                    StudyFile("1.2.3.10", "1.2.3.10.1", str(first)),
                    StudyFile("1.2.3.20", "1.2.3.20.1", str(second)),
                ],
                root,
            )

            extracted = Path(temporary_dir) / "extracted"
            extract_package(package, extracted)
            dicom_files = sorted(extracted.rglob("*.dcm"))
            self.assertEqual(len(dicom_files), 2)
            self.assertEqual(
                {path.read_bytes() for path in dicom_files},
                {b"first-series", b"second-series"},
            )
            manifest = json.loads((extracted / "manifest.json").read_text("utf-8"))
            self.assertEqual(manifest["fingerprint"], fingerprint)
            self.assertEqual(len(manifest["files"]), 2)

    def test_packager_rejects_indexed_path_outside_storage_root(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "storage"
            root.mkdir()
            outside = base / "outside.dcm"
            outside.write_bytes(b"not-allowed")

            with self.assertRaises(PackageBuildError):
                build_tar_zst(
                    base / "study.tar.zst",
                    "1.2.3",
                    [StudyFile("1.2.3.1", "1.2.3.1.1", str(outside))],
                    root,
                )

    def test_package_response_supports_http_range(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "storage"
            source = root / "study.dcm"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"dicom-payload")
            previous_root, previous_cache = packager.DICOM_ROOT, packager.CACHE_DIR
            try:
                packager.DICOM_ROOT = str(root)
                packager.CACHE_DIR = str(base / "cache")
                response = packager.get_or_build_package(
                    "1.2.3",
                    [StudyFile("1.2.3.1", "1.2.3.1.1", str(source))],
                )
                messages = asyncio.run(self._request_range(response))
            finally:
                packager.DICOM_ROOT = previous_root
                packager.CACHE_DIR = previous_cache

            start = next(message for message in messages if message["type"] == "http.response.start")
            body = b"".join(
                message.get("body", b"")
                for message in messages
                if message["type"] == "http.response.body"
            )
            self.assertEqual(start["status"], 206)
            self.assertEqual(len(body), 10)

    @staticmethod
    async def _request_range(response):
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/package",
            "raw_path": b"/package",
            "query_string": b"",
            "headers": [(b"range", b"bytes=0-9")],
            "client": ("test", 123),
            "server": ("test", 80),
            "root_path": "",
            "extensions": {},
        }
        await response(scope, receive, send)
        return messages

    def test_zip_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            package = base / "malicious.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../outside.dcm", b"payload")

            with self.assertRaises(UnsafeArchiveError):
                extract_package(package, base / "destination")
            self.assertFalse((base / "outside.dcm").exists())

    def test_tar_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            package = base / "malicious.tar"
            with tarfile.open(package, "w") as archive:
                link = tarfile.TarInfo("study/link.dcm")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../outside.dcm"
                archive.addfile(link)

            with self.assertRaises(UnsafeArchiveError):
                extract_package(package, base / "destination")


if __name__ == "__main__":
    unittest.main()
