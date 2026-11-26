from alembic import context

from task_system.config import Settings
from task_system.db import make_engine
from task_system.models import Base


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=Settings().db_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        migrate(connection)
    else:
        engine = make_engine(Settings())
        try:
            with engine.connect() as connection:
                migrate(connection)
        finally:
            engine.dispose()
