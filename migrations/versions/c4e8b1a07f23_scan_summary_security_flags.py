"""scan summary, security flags, and resonance columns"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "c4e8b1a07f23"
down_revision = "9d1de515558b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("security", sa.Column("sector", sa.String(length=100), nullable=True))
    op.add_column(
        "security",
        sa.Column("is_st", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "security",
        sa.Column(
            "security_kind",
            sa.String(length=16),
            nullable=False,
            server_default="stock",
        ),
    )
    op.add_column(
        "scan_result",
        sa.Column("resonance_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "scan_result",
        sa.Column("sector_strength", sa.Numeric(precision=18, scale=6), nullable=True),
    )
    op.create_index(
        "ix_scan_result_symbol_trade_date",
        "scan_result",
        ["symbol", "trade_date"],
        unique=False,
    )
    op.create_table(
        "scan_summary",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("adjustment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("market_regime", sa.String(length=20), nullable=False),
        sa.Column("benchmark", sa.String(length=32), nullable=True),
        sa.Column("universe_count", sa.Integer(), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("resonance_count", sa.Integer(), nullable=False),
        sa.Column("strategy_hit_counts", sa.JSON(), nullable=False),
        sa.Column("sector_strength", sa.JSON(), nullable=False),
        sa.Column("filter_counts", sa.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["job_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market",
            "trade_date",
            "source",
            "adjustment",
            name="uq_scan_summary_day",
        ),
    )
    op.create_index(op.f("ix_scan_summary_run_id"), "scan_summary", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_scan_summary_trade_date"), "scan_summary", ["trade_date"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_scan_summary_trade_date"), table_name="scan_summary")
    op.drop_index(op.f("ix_scan_summary_run_id"), table_name="scan_summary")
    op.drop_table("scan_summary")
    op.drop_index("ix_scan_result_symbol_trade_date", table_name="scan_result")
    op.drop_column("scan_result", "sector_strength")
    op.drop_column("scan_result", "resonance_count")
    op.drop_column("security", "security_kind")
    op.drop_column("security", "is_st")
    op.drop_column("security", "sector")
