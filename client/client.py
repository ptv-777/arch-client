
import sys, os, io, zipfile, tarfile, tempfile, subprocess, shutil, requests
from PySide6.QtWidgets import (QApplication, QWidget, QLineEdit, QFormLayout, QPushButton, 
                               QTableWidget, QTableWidgetItem, QFileDialog, QHBoxLayout, QMessageBox)
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
        try:
            r = requests.get(f"{API_BASE}/package", params={"study_uid": suid}, stream=True, timeout=600)
            r.raise_for_status()
            pkg_path = os.path.join(DOWNLOAD_DIR, f"{suid}.tar.zst")
            with open(pkg_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return
        # распаковка
        target_dir = QFileDialog.getExistingDirectory(self, "Выберите папку для распаковки", DOWNLOAD_DIR)
        if not target_dir:
            return
        # zstd -> tar
        import zstandard as zstd
        try:
            with open(pkg_path, "rb") as src:
                dctx = zstd.ZstdDecompressor()
                with dctx.stream_reader(src) as reader:
                    # распакуем tar из потока
                    with tarfile.open(fileobj=reader, mode="r|") as tf:
                        tf.extractall(path=target_dir)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка распаковки", str(e))
            return
        QMessageBox.information(self, "Готово", f"Распаковано в: {target_dir}")

    def open_viewer(self):
        # открываем просмотрщик на выбранной папке (после распаковки)
        d = QFileDialog.getExistingDirectory(self, "Выберите папку с DICOM", DOWNLOAD_DIR)
        if not d:
            return
        try:
            subprocess.Popen([VIEWER_CMD, d])
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось запустить просмотрщик: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App(); w.resize(1000, 600); w.show()
    sys.exit(app.exec())
