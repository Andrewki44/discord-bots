"""add persistent view table

Revision ID: 7a12e2e190ba
Revises: 402ad305b51b
Create Date: 2024-02-19 08:29:41.596686

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7a12e2e190ba"
down_revision = "402ad305b51b"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "persistent_view",
        sa.Column("view_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("view_type", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("view_id", name=op.f("pk_persistent_view")),
    )
    with op.batch_alter_table("in_progress_game", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("game_view_id", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("prediction_view_id", sa.String(), nullable=True)
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_in_progress_game_game_view_id_persistent_view"),
            "persistent_view",
            ["game_view_id"],
            ["view_id"],
        )
        batch_op.create_foreign_key(
            batch_op.f(
                "fk_in_progress_game_prediction_view_id_persistent_view"
            ),
            "persistent_view",
            ["prediction_view_id"],
            ["view_id"],
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("in_progress_game", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f(
                "fk_in_progress_game_prediction_view_id_persistent_view"
            ),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            batch_op.f("fk_in_progress_game_game_view_id_persistent_view"),
            type_="foreignkey",
        )
        batch_op.drop_column("prediction_view_id")
        batch_op.drop_column("game_view_id")

    op.drop_table("persistent_view")
    # ### end Alembic commands ###
