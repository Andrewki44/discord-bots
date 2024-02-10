"""add queue.vote_threshold

Revision ID: 62f85cf1f1d6
Revises: b29ddf680a84
Create Date: 2024-02-08 09:00:32.513610

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "62f85cf1f1d6"
down_revision = "b29ddf680a84"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("queue", schema=None) as batch_op:
        batch_op.add_column(sa.Column("vote_threshold", sa.Integer(), nullable=True))

    op.execute(
        "UPDATE queue SET vote_threshold = ROUND(CAST(size AS FLOAT) * 2 / 3) WHERE size IS NOT NULL"
    )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("queue", schema=None) as batch_op:
        batch_op.drop_column("vote_threshold")

    # ### end Alembic commands ###
