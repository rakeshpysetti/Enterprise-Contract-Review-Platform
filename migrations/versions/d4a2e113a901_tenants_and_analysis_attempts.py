"""Add tenant ownership and analysis attempt fencing.

Revision ID: d4a2e113a901
Revises: c2b09b0030df
"""

import sqlalchemy as sa
from alembic import op

revision = "d4a2e113a901"
down_revision = "c2b09b0030df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="legacy"),
    )
    op.create_index("ix_contracts_tenant_id", "contracts", ["tenant_id"])
    op.add_column(
        "contracts", sa.Column("analysis_attempt_id", sa.Uuid(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("contracts", "analysis_attempt_id")
    op.drop_index("ix_contracts_tenant_id", table_name="contracts")
    op.drop_column("contracts", "tenant_id")
