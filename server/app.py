
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from .db import SessionLocal, engine, Base, Patient, Study, Series, Instance
from .utils import normalize_name
from .packager import get_or_build_package
from .config import DICOM_ROOT

from typing import List, Dict

app = FastAPI(title="DICOM Index & Packaging API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаём таблицы, если их нет
Base.metadata.create_all(bind=engine)

@app.get("/health") 
def health():
    return {"status":"ok"}

@app.get("/search")
def search(
    name: str = Query(..., description="ФИО пациента"),
    dob: str = Query(..., description="Дата рождения в формате YYYYMMDD"),
    sex: str | None = Query(None, description="Пол (M/F)"),
    year: int | None = Query(None, description="Год исследования"),
):
    nname = normalize_name(name)
    with SessionLocal() as s:
        # Найдём пациентов
        q_pat = select(Patient.id).where(Patient.patient_name_norm == nname, Patient.birth_date == dob)
        if sex:
            q_pat = q_pat.where(Patient.sex == sex)
        pat_ids = [r[0] for r in s.execute(q_pat).all()]
        if not pat_ids:
            return []
        # Исследования по пациентам
        q = (
            select(
                Study.study_uid,
                Study.study_date,
                func.count(Instance.sop_uid).label("files"),
                func.coalesce(func.sum(Instance.size_bytes), 0).label("bytes"),
            )
            .join(Series, Series.study_uid == Study.study_uid)
            .join(Instance, Instance.series_uid == Series.series_uid)
            .where(Study.patient_fk.in_(pat_ids))
            .group_by(Study.study_uid, Study.study_date)
            .order_by(func.coalesce(func.sum(Instance.size_bytes), 0).desc())
        )
        if year:
            q = q.where(Study.study_date.like(f"{year}%"))
        rows = s.execute(q).all()
        out: List[Dict] = []
        for suid, sdate, files, bytes_ in rows:
            out.append({
                "study_uid": suid,
                "study_date": sdate,
                "files": int(files),
                "bytes": int(bytes_),
            })
        return out

@app.get("/package")
def package(study_uid: str = Query(...)):
    # собираем пути файлов исследования
    with SessionLocal() as s:
        q = (
            select(Instance.path)
            .join(Series, Series.series_uid == Instance.series_uid)
            .where(Series.study_uid == study_uid)
        )
        paths = [r[0] for r in s.execute(q).scalars().all()]
        if not paths:
            raise HTTPException(404, detail="Study not found or empty")
    return get_or_build_package(study_uid, paths)
