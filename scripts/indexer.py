
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pydicom
from pydicom.errors import InvalidDicomError
from sqlalchemy import select
from server.db import SessionLocal, Base, engine, Patient, Study, Series, Instance
from server.utils import normalize_name

TAGS = ["StudyInstanceUID","SeriesInstanceUID","SOPInstanceUID",
        "PatientID","PatientName","PatientBirthDate","PatientSex",
        "StudyDate","Modality","TransferSyntaxUID"]

def process_file(p: Path) -> tuple[bool,str]:
    try:
        ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True, specific_tags=TAGS)
    except InvalidDicomError:
        return False, "invalid"
    except Exception as e:
        return False, "error"
    # minimal required tags
    for key in ("StudyInstanceUID","SeriesInstanceUID","SOPInstanceUID"):
        if not getattr(ds, key, None):
            return False, "missing_tags"
    # write to DB (upserts)
    try:
        with SessionLocal() as s:
            patient_id = str(getattr(ds, "PatientID", ""))
            patient_name = str(getattr(ds, "PatientName", ""))
            birth_date = str(getattr(ds, "PatientBirthDate", ""))
            sex = str(getattr(ds, "PatientSex", ""))
            study_uid = str(ds.StudyInstanceUID); series_uid = str(ds.SeriesInstanceUID); sop_uid = str(ds.SOPInstanceUID)
            study_date = str(getattr(ds, "StudyDate", ""))
            ts = str(getattr(ds, "TransferSyntaxUID", ""))
            # patient
            p_row = s.execute(select(Patient).where(Patient.patient_id==patient_id, Patient.birth_date==birth_date)).scalar_one_or_none()
            if not p_row:
                p_row = Patient(patient_id=patient_id, birth_date=birth_date, sex=sex,
                                patient_name=patient_name, patient_name_norm=normalize_name(patient_name))
                s.add(p_row); s.flush()
            st = s.get(Study, study_uid)
            if not st:
                st = Study(study_uid=study_uid, patient_fk=p_row.id, study_date=study_date, modality=str(getattr(ds, "Modality", "")))
                s.add(st)
            se = s.get(Series, series_uid)
            if not se:
                se = Series(series_uid=series_uid, study_uid=study_uid)
                s.add(se)
            inst = s.get(Instance, sop_uid)
            if not inst:
                size = Path(p).stat().st_size
                inst = Instance(sop_uid=sop_uid, series_uid=series_uid, transfer_syntax=ts, size_bytes=size, path=str(p))
                s.add(inst)
            s.commit()
        return True, "ok"
    except Exception as e:
        return False, "db_error"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Корень с DICOM-файлами (каноническая структура или любая)")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    paths = [p for p in Path(args.root).rglob("*") if p.is_file()]
    ok = bad = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(process_file, p) for p in paths]
        for f in as_completed(futs):
            good, _ = f.result()
            if good: ok += 1
            else: bad += 1
    print(f"indexed ok={ok} bad={bad}")

if __name__ == "__main__":
    main()
