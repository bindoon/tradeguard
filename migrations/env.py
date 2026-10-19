from alembic import context

from tradeguard.db import engine
from tradeguard.db.models import Base

with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
