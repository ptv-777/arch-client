
import io, os, tarfile, hashlib, time
from pathlib import Path
from typing import Iterable, Tuple
import zstandard as zstd
from fastapi.responses import FileResponse
from .config import CACHE_DIR

def _manifest_entry(relpath: str, abspath: str):
    st = os.stat(abspath)
    return {
        "path": relpath,
        "size": st.st_size,
        "mtime": int(st.st_mtime)
    }

def build_tar_zst(package_path: Path, base_dir: Path, files: Iterable[Tuple[str, str]]):
    # files: iterator of (relpath, abspath)
    tmp_tar = package_path.with_suffix(".partial.tar")
    tmp_zst = package_path.with_suffix(".partial.tar.zst")
    # 1) tar
    with tarfile.open(tmp_tar, mode="w") as tf:
        # добавим manifest.json в корень
        manifest = []
        for rel, abs_ in files:
            manifest.append(_manifest_entry(rel, abs_))
            tf.add(abs_, arcname=rel, recursive=False)
        # manifest
        import json, tempfile
        data = json.dumps({"version":"1","generated":int(time.time()),"files":manifest}, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    # 2) zstd
    cctx = zstd.ZstdCompressor(level=6)
    with open(tmp_tar, "rb") as src, open(tmp_zst, "wb") as dst:
        cctx.copy_stream(src, dst)
    os.remove(tmp_tar)
    os.replace(tmp_zst, package_path)

def get_or_build_package(study_uid: str, file_list: Iterable[str]) -> FileResponse:
    # file_list: absolute paths to dicom files belonging to the study
    os.makedirs(CACHE_DIR, exist_ok=True)
    # разложим в архиве как StudyUID/<basename>
    rel_abs = [(f"{study_uid}/" + os.path.basename(p), p) for p in file_list]
    # ключ архива — study_uid
    package_path = Path(CACHE_DIR) / f"{study_uid}.tar.zst"
    if not package_path.exists():
        build_tar_zst(package_path, Path("/"), rel_abs)
    return FileResponse(str(package_path), media_type="application/zstd", filename=f"{study_uid}.tar.zst")
