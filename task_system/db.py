from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from task_system.config import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.db_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def make_sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
