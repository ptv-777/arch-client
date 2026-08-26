
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from .config import CORS_ORIGINS
from .db import Base, Instance, Patient, Series, SessionLocal, Study, engine
from .packager import PackageBuildError, get_or_build_package
from .repository import get_study_files
from .utils import normalize_name

app = FastAPI(title="DICOM Index & Packaging API")
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Authorization", "Content-Type", "Range"],
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
        out: list[dict] = []
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
    with SessionLocal() as s:
        files = get_study_files(s, study_uid)
        if not files:
            raise HTTPException(404, detail="Study not found or empty")
    try:
        return get_or_build_package(study_uid, files)
    except PackageBuildError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
