
import sys, os, io, zipfile, tarfile, tempfile, subprocess, shutil, requests, time, re
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QWidget, QLineEdit, QFormLayout, QPushButton,
                               QTableWidget, QTableWidgetItem, QFileDialog, QHBoxLayout, QMessageBox,
                               QLabel, QProgressBar)
from PySide6.QtCore import Qt
from .config import API_BASE, DOWNLOAD_DIR, VIEWER_CMD

def human_mb(n):
    return f"{n/1024/1024:.1f} MB"

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DICOM Поиск и загрузка")
        self.name = QLineEdit()
        self.dob  = QLineEdit()  # YYYYMMDD
        self.sex  = QLineEdit()  # M/F (опц.)
        self.year = QLineEdit()  # 2024 (опц.)
        self.btn_search = QPushButton("Искать")
        self.btn_search.clicked.connect(self.do_search)
        self.tbl = QTableWidget(0,4)
        self.tbl.setHorizontalHeaderLabels(["StudyUID","Дата","Файлов","Объём"])
        self.btn_dl = QPushButton("Скачать выбранное исследование")
        self.btn_dl.clicked.connect(self.do_download)
        self.btn_view = QPushButton("Открыть в просмотрщике (папка)")
        self.btn_view.clicked.connect(self.open_viewer)
        self.status = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Готово")

        form = QFormLayout()
        form.addRow("ФИО:", self.name)
        form.addRow("Дата рождения (YYYYMMDD):", self.dob)
        form.addRow("Пол (M/F, опц.):", self.sex)
        form.addRow("Год (опц.):", self.year)

        h = QHBoxLayout()
        h.addWidget(self.btn_search)
        h.addWidget(self.btn_dl)
        h.addWidget(self.btn_view)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(self.tbl)
        layout.addRow(h)
        layout.addRow(self.progress)
        layout.addRow(self.status)

        self.results = []

    def do_search(self):
        params = {"name": self.name.text().strip(), "dob": self.dob.text().strip()}
        if self.sex.text().strip(): params["sex"] = self.sex.text().strip()
        if self.year.text().strip(): params["year"] = int(self.year.text().strip())
        try:
            r = requests.get(f"{API_BASE}/search", params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return
        self.results = data
        self.tbl.setRowCount(len(data))
        for i, row in enumerate(data):
            self.tbl.setItem(i,0,QTableWidgetItem(row["study_uid"]))
            self.tbl.setItem(i,1,QTableWidgetItem(row.get("study_date","")))
            self.tbl.setItem(i,2,QTableWidgetItem(str(row["files"])))
            self.tbl.setItem(i,3,QTableWidgetItem(human_mb(row["bytes"])))

    def current_study(self):
        i = self.tbl.currentRow()
        if i < 0:
            QMessageBox.information(self, "Внимание", "Выберите строку в таблице результатов.")
            return None
        return self.tbl.item(i,0).text()

    def do_download(self):
        suid = self.current_study()
        if not suid:
            return
        target_dir = QFileDialog.getExistingDirectory(self, "Выберите папку для распаковки", DOWNLOAD_DIR)
        if not target_dir:
            return
        pkg_path = self._download_package(suid)
        if not pkg_path:
            return
        if not self._extract_package(Path(pkg_path), Path(target_dir)):
            return
        QMessageBox.information(self, "Готово", f"Распаковано в: {target_dir}")
        now = time.time()
        os.utime(target_dir, (now, now))
        try:
            os.remove(pkg_path)
        except OSError:
            pass

    def open_viewer(self):
        # открываем просмотрщик на выбранной папке (после распаковки)
        d = QFileDialog.getExistingDirectory(self, "Выберите папку с DICOM", DOWNLOAD_DIR)
        if not d:
            return
        try:
            subprocess.Popen([VIEWER_CMD, d])
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось запустить просмотрщик: {e}")

    def _download_package(self, suid: str) -> str | None:
        self.progress.setFormat("Скачивание %p%")
        self.progress.setRange(0, 0)  # неопределённый прогресс
        self.progress.setValue(0)
        self.status.setText("Подготовка к скачиванию...")
        QApplication.processEvents()
        try:
            r = requests.get(f"{API_BASE}/package", params={"study_uid": suid}, stream=True, timeout=600)
            r.raise_for_status()
        except Exception as e:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Ошибка")
            QMessageBox.critical(self, "Ошибка", str(e))
            return None

        filename = self._resolve_filename(r, suid)
        pkg_path = Path(DOWNLOAD_DIR) / filename
        total = int(r.headers.get("Content-Length") or 0)
        if total:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        downloaded = 0
        try:
            with open(pkg_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded * 100 / total)
                        self.progress.setValue(min(pct, 100))
                        self.status.setText(f"Скачано {human_mb(downloaded)} из {human_mb(total)}")
                        QApplication.processEvents()
        except Exception as e:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Ошибка")
            QMessageBox.critical(self, "Ошибка", f"Не удалось скачать архив: {e}")
            return None
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("Загрузка завершена")
        self.status.setText(f"Файл сохранён: {pkg_path}")
        return str(pkg_path)

    def _resolve_filename(self, response: requests.Response, suid: str) -> str:
        cd = response.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            return m.group(1)
        ctype = response.headers.get("Content-Type", "")
        if "zip" in ctype:
            return f"{suid}.zip"
        if "tar" in ctype:
            return f"{suid}.tar"
        if "zstd" in ctype:
            return f"{suid}.tar.zst"
        return f"{suid}.pkg"

    def _extract_package(self, pkg_path: Path, target_dir: Path) -> bool:
        self.progress.setFormat("Распаковка %p%")
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.status.setText("Распаковка архива...")
        QApplication.processEvents()

        try:
            suffix = "".join(pkg_path.suffixes).lower()
            if suffix.endswith(".tar.zst"):
                import zstandard as zstd
                with open(pkg_path, "rb") as src:
                    dctx = zstd.ZstdDecompressor()
                    with dctx.stream_reader(src) as reader:
                        with tarfile.open(fileobj=reader, mode="r|") as tf:
                            tf.extractall(path=target_dir)
            elif suffix.endswith(".zip"):
                with zipfile.ZipFile(pkg_path, "r") as zf:
                    zf.extractall(path=target_dir)
            elif suffix.endswith(".tar") or suffix.endswith(".tgz") or suffix.endswith(".tar.gz"):
                with tarfile.open(pkg_path, mode="r:*") as tf:
                    tf.extractall(path=target_dir)
            else:
                QMessageBox.warning(self, "Неизвестный формат", f"Неизвестный тип архива: {pkg_path.name}")
                return False
        except Exception as e:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Ошибка")
            QMessageBox.critical(self, "Ошибка распаковки", str(e))
            return False
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("Готово")
        self.status.setText(f"Распаковано в: {target_dir}")
        return True

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App(); w.resize(1000, 600); w.show()
    sys.exit(app.exec())
