
"""Скелет ISO-инжеста.
Запуск: python -m server.ingest.ingest /path/to/file.iso

Примечание: монтирование ISO зависит от ОС. На Linux можно использовать:
  sudo mount -o loop,ro file.iso /mnt/iso
Далее обойти файлы и обработать DICOM.

Ниже — каркас: разбор каталога, чтение заголовков, дедуп (упрощённо), раскладка.
"""
from pathlib import Path
import sys, shutil, hashlib, os
import pydicom
from pydicom.errors import InvalidDicomError
from sqlalchemy import select
from ..config import DICOM_ROOT
from ..db import SessionLocal, Patient, Study, Series, Instance, Base, engine
from ..utils import normalize_name

def ensure_dirs_for(uid: str) -> Path:
    # Фан-аут по первым 4 символам sha1(study_uid)
    import hashlib
    h = hashlib.sha1(uid.encode("utf-8")).hexdigest()
    base = Path(DICOM_ROOT) / "studies" / h[:2] / h[2:4] / uid
    base.mkdir(parents=True, exist_ok=True)
    return base

def upsert_from_header(ds, src_path: Path):
    if not getattr(ds, "StudyInstanceUID", None) or not getattr(ds, "SeriesInstanceUID", None) or not getattr(ds, "SOPInstanceUID", None):
        return False
    patient_id = str(getattr(ds, "PatientID", ""))
    patient_name = str(getattr(ds, "PatientName", ""))
    birth_date = str(getattr(ds, "PatientBirthDate", ""))
    sex = str(getattr(ds, "PatientSex", ""))
    study_uid = str(ds.StudyInstanceUID)
    series_uid = str(ds.SeriesInstanceUID)
    sop_uid = str(ds.SOPInstanceUID)
    study_date = str(getattr(ds, "StudyDate", ""))
    ts = str(getattr(ds, "file_meta", {}).get("TransferSyntaxUID", getattr(ds, "TransferSyntaxUID", "")))

    with SessionLocal() as s:
        # patient (грубый upsert)
        p = s.execute(select(Patient).where(Patient.patient_id==patient_id, Patient.birth_date==birth_date)).scalar_one_or_none()
        if not p:
            p = Patient(patient_id=patient_id, birth_date=birth_date, sex=sex,
                        patient_name=patient_name, patient_name_norm=normalize_name(patient_name))
            s.add(p)
            s.flush()
        else:
            # возможно обновим имя/пол
            if not p.patient_name:
                p.patient_name = patient_name
                p.patient_name_norm = normalize_name(patient_name)
            if not p.sex and sex:
                p.sex = sex

        st = s.get(Study, study_uid)
        if not st:
            st = Study(study_uid=study_uid, patient_fk=p.id, study_date=study_date, modality=str(getattr(ds, "Modality", "")))
            s.add(st)

        se = s.get(Series, series_uid)
        if not se:
            se = Series(series_uid=series_uid, study_uid=study_uid)
            s.add(se)

        inst = s.get(Instance, sop_uid)
        if inst:
            # дубликат — упрощение: пропускаем
            return False
        dest_dir = ensure_dirs_for(study_uid) / series_uid
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{sop_uid}.dcm"
        shutil.copy2(src_path, dest)
        size = dest.stat().st_size
        inst = Instance(sop_uid=sop_uid, series_uid=series_uid, transfer_syntax=ts, size_bytes=size, path=str(dest))
        s.add(inst)
        s.commit()
        return True

def process_dir(root: Path):
    cnt_add = cnt_skip = cnt_err = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True,
                                 specific_tags=["StudyInstanceUID","SeriesInstanceUID","SOPInstanceUID",
                                                "PatientID","PatientName","PatientBirthDate","PatientSex",
                                                "StudyDate","Modality","TransferSyntaxUID"]
                                 )
        except InvalidDicomError:
            cnt_err += 1
            continue
        except Exception:
            cnt_err += 1
            continue
        ok = upsert_from_header(ds, p)
        if ok:
            cnt_add += 1
        else:
            cnt_skip += 1
    print(f"added={cnt_add} skip={cnt_skip} err={cnt_err}")

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    if len(sys.argv) < 2:
        print("Usage: python -m server.ingest.ingest /path/to/mounted_iso_dir")
        sys.exit(1)
    process_dir(Path(sys.argv[1]))
