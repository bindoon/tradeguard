"""Persist coverage so console requests never aggregate historical daily bars."""

import sqlalchemy as sa
from alembic import op

revision = "a73f20b61d94"
down_revision = "e82b9a41d063"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bar_date_coverage",
        sa.Column("market", sa.String(8), primary_key=True),
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("adjustment", sa.String(16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("bar_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "bar_series_coverage",
        sa.Column("symbol", sa.String(32), sa.ForeignKey("security.symbol"), primary_key=True),
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("adjustment", sa.String(16), primary_key=True),
        sa.Column("first_date", sa.Date(), nullable=False),
    )
    # A one-time, local backfill. No source database or provider is contacted.
    op.execute(
        sa.text("""
        INSERT INTO bar_date_coverage (market, source, adjustment, trade_date, bar_count)
        SELECT s.market, b.source, b.adjustment, b.trade_date, COUNT(*)
        FROM daily_bar b JOIN security s ON s.symbol = b.symbol
        GROUP BY s.market, b.source, b.adjustment, b.trade_date
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO bar_series_coverage (symbol, source, adjustment, first_date)
        SELECT symbol, source, adjustment, MIN(trade_date)
        FROM daily_bar GROUP BY symbol, source, adjustment
    """)
    )


def downgrade():
    op.drop_table("bar_series_coverage")
    op.drop_table("bar_date_coverage")
