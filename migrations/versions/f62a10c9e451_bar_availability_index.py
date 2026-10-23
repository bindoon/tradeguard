"""Cover source/adjustment/date availability without reading full OHLCV rows."""

from alembic import op

revision = "f62a10c9e451"
down_revision = "c4e8b1a07f23"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_daily_bar_source_adjustment_date", "daily_bar", ["source", "adjustment", "trade_date"]
    )


def downgrade():
    op.drop_index("ix_daily_bar_source_adjustment_date", table_name="daily_bar")
