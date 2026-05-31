import os

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from .database import engine
from . import models as _models  # noqa: F401 — registers ORM classes on Base.metadata


def _alembic_cfg() -> AlembicConfig:
    ini_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    )
    return AlembicConfig(ini_path)


def init_db() -> None:
    cfg = _alembic_cfg()

    # Detect existing databases that pre-date Alembic (no alembic_version table).
    # Stamp them at the baseline revision so migration 0002 runs cleanly.
    need_stamp = False
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        if ctx.get_current_revision() is None:
            if "job_applications" in inspect(engine).get_table_names():
                need_stamp = True

    if need_stamp:
        alembic_command.stamp(cfg, "0001")

    alembic_command.upgrade(cfg, "head")


if __name__ == "__main__":
    init_db()
    print("Database schema initialized.")
