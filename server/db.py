
from sqlalchemy import create_engine, String, Integer, BigInteger, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool
from .config import DB_URL

class Base(DeclarativeBase):
    pass

class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(String(128), nullable=True)
    patient_name: Mapped[str] = mapped_column(Text, nullable=True)
    patient_name_norm: Mapped[str] = mapped_column(Text, index=True, nullable=True)
    birth_date: Mapped[str] = mapped_column(String(16), index=True, nullable=True)
    sex: Mapped[str] = mapped_column(String(8), nullable=True)

class Study(Base):
    __tablename__ = "studies"
    study_uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    patient_fk: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    study_date: Mapped[str] = mapped_column(String(16), index=True, nullable=True)
    modality: Mapped[str] = mapped_column(String(16), nullable=True)

class Series(Base):
    __tablename__ = "series"
    series_uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    study_uid: Mapped[str] = mapped_column(ForeignKey("studies.study_uid"))

class Instance(Base):
    __tablename__ = "instances"
    sop_uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    series_uid: Mapped[str] = mapped_column(ForeignKey("series.series_uid"))
    transfer_syntax: Mapped[str] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=True)
    path: Mapped[str] = mapped_column(Text, unique=True)

def make_engine():
    if DB_URL.startswith("sqlite"):
        engine = create_engine(DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(DB_URL, pool_pre_ping=True)
    return engine

engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
