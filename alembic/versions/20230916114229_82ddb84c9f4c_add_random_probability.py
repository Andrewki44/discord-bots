"""Add random probability

Revision ID: 82ddb84c9f4c
Revises: 4cb0a6b616c9
Create Date: 2023-09-16 11:42:29.435012

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "82ddb84c9f4c"
down_revision = "4cb0a6b616c9"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("rotation_map", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "random_probability",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("rotation_map", schema=None) as batch_op:
        batch_op.drop_column("random_probability")

    # ### end Alembic commands ###