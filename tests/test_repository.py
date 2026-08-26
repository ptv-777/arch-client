import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.db import Base, Instance, Patient, Series, Study
from server.repository import get_study_files


class StudyRepositoryTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_returns_complete_paths_in_stable_series_order(self):
        with self.Session.begin() as session:
            patient = Patient(
                patient_id="patient-1",
                patient_name="TEST",
                patient_name_norm="test",
                birth_date="19700101",
                sex="M",
            )
            session.add(patient)
            session.flush()
            session.add(Study(study_uid="1.2", patient_fk=patient.id, study_date="20250101"))
            session.add_all(
                [
                    Series(series_uid="1.2.20", study_uid="1.2"),
                    Series(series_uid="1.2.10", study_uid="1.2"),
                ]
            )
            session.add_all(
                [
                    Instance(
                        sop_uid="1.2.20.1",
                        series_uid="1.2.20",
                        size_bytes=20,
                        path="/archive/series-20/IMG_00001.dcm",
                    ),
                    Instance(
                        sop_uid="1.2.10.1",
                        series_uid="1.2.10",
                        size_bytes=10,
                        path="/archive/series-10/IMG_00001.dcm",
                    ),
                ]
            )

        with self.Session() as session:
            files = get_study_files(session, "1.2")

        self.assertEqual(
            [item.path for item in files],
            [
                "/archive/series-10/IMG_00001.dcm",
                "/archive/series-20/IMG_00001.dcm",
            ],
        )


if __name__ == "__main__":
    unittest.main()
