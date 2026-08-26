from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Instance, Series
from .packager import StudyFile


def get_study_files(session: Session, study_uid: str) -> list[StudyFile]:
    """Return complete file records in a stable order for packaging."""
    query = (
        select(Series.series_uid, Instance.sop_uid, Instance.path)
        .join(Instance, Instance.series_uid == Series.series_uid)
        .where(Series.study_uid == study_uid)
        .order_by(Series.series_uid, Instance.sop_uid)
    )
    return [
        StudyFile(series_uid=series_uid, sop_uid=sop_uid, path=path)
        for series_uid, sop_uid, path in session.execute(query).all()
    ]
