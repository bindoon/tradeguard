"""Frozen backtest inputs/reports and independently managed plugin enablement."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "b82e14d8a609"
down_revision = "a73f20b61d94"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "strategy_plugin_state",
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "backtest_artifact",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["job_run.id"]),
        sa.PrimaryKeyConstraint("run_id", "key"),
    )


def downgrade():
    op.drop_table("backtest_artifact")
    op.drop_table("strategy_plugin_state")
