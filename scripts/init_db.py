"""Initialize the database schema using Alembic migrations."""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic.config import Config
from alembic import command
from config.settings import settings
from loguru import logger


def init_database():
    """Initialize database by running Alembic migrations."""
    logger.info(f"Initializing database at {settings.database_url}")
    
    # Configure Alembic
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("+aiosqlite", ""))
    
    # Run migrations to head
    try:
        command.upgrade(alembic_cfg, "head")
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


if __name__ == "__main__":
    init_database()
