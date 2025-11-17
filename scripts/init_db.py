
from server.db import Base, engine
Base.metadata.create_all(bind=engine)
print("DB initialized.")
