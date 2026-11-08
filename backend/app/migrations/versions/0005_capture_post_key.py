"""A post's identity on captures, so the same post is recognised across its link forms.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Short links (vm.tiktok.com) have no ID until they're resolved, so those stay empty here.
TIKTOK_POST = re.compile(r"^https?://([\w-]+\.)*tiktokv?\.com/.*?/(?:video|photo|v)/(\d+)")


def upgrade() -> None:
    with op.batch_alter_table("captures", schema=None) as batch_op:
        batch_op.add_column(sa.Column("post_key", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_captures_post_key", ["post_key"])

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, url FROM captures WHERE url LIKE '%tiktok%'")).all()
    for capture_id, url in rows:
        if match := TIKTOK_POST.search(url):
            conn.execute(
                sa.text("UPDATE captures SET post_key = :key WHERE id = :id"),
                {"key": f"tiktok:{match.group(2)}", "id": capture_id},
            )


def downgrade() -> None:
    with op.batch_alter_table("captures", schema=None) as batch_op:
        batch_op.drop_index("ix_captures_post_key")
        batch_op.drop_column("post_key")
