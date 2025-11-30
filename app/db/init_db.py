# app/db/init_db.py

from sqlalchemy import text
from app.db.session import engine
from app.db.base import Base


def init_db() -> None:
    """
    Initialize / patch the database schema.

    - Base.metadata.create_all() creates any missing tables.
    - Then we run a few lightweight, idempotent ALTERs to keep older
      dev databases compatible with the current models.
    """
    # 1) Create all tables from SQLAlchemy models (no-op if they already exist)
    Base.metadata.create_all(bind=engine)

    # 2) Lightweight schema patches for existing databases
    #    Use a single transaction so we don't need explicit commit().
    with engine.begin() as conn:
        # --------------------------------------------------
        # Ensure new USER columns exist (subscription + free tier)
        # --------------------------------------------------
        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'free';
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS has_costco_membership BOOLEAN NOT NULL DEFAULT FALSE;
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS has_costco_addon BOOLEAN NOT NULL DEFAULT FALSE;
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS free_items_limit INTEGER NOT NULL DEFAULT 5;
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS free_plan_runs_limit INTEGER NOT NULL DEFAULT 5;
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS free_plan_runs_used INTEGER NOT NULL DEFAULT 0;
                """
            )
        )

        # --------------------------------------------------
        # Ensure new WATCHLIST columns exist
        # --------------------------------------------------
        conn.execute(
            text(
                """
                ALTER TABLE watchlist_items
                ADD COLUMN IF NOT EXISTS item_intent_id UUID;
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE watchlist_items
                ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE watchlist_items
                ADD COLUMN IF NOT EXISTS last_price NUMERIC(10, 2);
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE watchlist_items
                ADD COLUMN IF NOT EXISTS previous_price NUMERIC(10, 2);
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE watchlist_items
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
                """
            )
        )

        conn.execute(
            text(
                """
                ALTER TABLE watchlist_items
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
                """
            )
        )

        # --- Relax raw_query NOT NULL only if the column actually exists ---
        result = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'watchlist_items';
                """
            )
        )
        existing_columns = {row[0] for row in result}

        if "raw_query" in existing_columns:
            conn.execute(
                text(
                    """
                    ALTER TABLE watchlist_items
                    ALTER COLUMN raw_query DROP NOT NULL;
                    """
                )
            )
