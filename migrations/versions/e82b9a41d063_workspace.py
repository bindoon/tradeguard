"""Local watchlist, price conditions and deduplicated inbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "e82b9a41d063"
down_revision = "f62a10c9e451"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("watch_item", "price_alert", "notification"):
        columns = [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("market", sa.String(8), nullable=False),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column("adjustment", sa.String(16), nullable=False),
            sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        ]
        if table == "watch_item":
            columns += [
                sa.Column(
                    "symbol", sa.String(32), sa.ForeignKey("security.symbol"), nullable=False
                ),
                sa.Column("reason", sa.Text(), nullable=False),
                sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("job_run.id")),
                sa.Column("last_signal_run_id", sa.String(36)),
                sa.UniqueConstraint("symbol", "source", "adjustment", name="uq_watch_scope"),
            ]
        elif table == "price_alert":
            columns += [
                sa.Column(
                    "symbol", sa.String(32), sa.ForeignKey("security.symbol"), nullable=False
                ),
                sa.Column("condition", sa.String(8), nullable=False),
                sa.Column("target_price", sa.Numeric(24, 8), nullable=False),
                sa.Column("active", sa.Boolean(), nullable=False),
            ]
        else:
            columns += [
                sa.Column("symbol", sa.String(32)),
                sa.Column("event_key", sa.String(64), nullable=False, unique=True),
                sa.Column("kind", sa.String(30), nullable=False),
                sa.Column("title", sa.String(200), nullable=False),
                sa.Column("evidence", sa.JSON(), nullable=False),
                sa.Column("read", sa.Boolean(), nullable=False),
            ]
        op.create_table(table, *columns)
        op.create_index(f"ix_{table}_market", table, ["market"])


def downgrade():
    for table in ("notification", "price_alert", "watch_item"):
        op.drop_index(f"ix_{table}_market", table_name=table)
        op.drop_table(table)
