"""Initialize the database schema."""
from sqlalchemy import create_engine
from models.trade import Base
from config.settings import settings

engine = create_engine(settings.database_url)
Base.metadata.create_all(engine)
print("Database initialized.")
