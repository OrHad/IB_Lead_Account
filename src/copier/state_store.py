"""Persistent state store for tracking order mappings."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import logging


@dataclass
class OrderMapping:
    """Mapping between primary order and follower orders."""
    primary_order_id: int
    follower_account: str
    follower_order_id: int
    symbol: str
    action: str  # BUY/SELL
    quantity: float
    order_type: str
    status: str  # SUBMITTED, FILLED, CANCELLED, REJECTED
    created_at: str
    updated_at: str


class StateStore:
    """SQLite-based persistent state store."""

    def __init__(self, db_path: str):
        """Initialize the state store."""
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS order_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    primary_order_id INTEGER NOT NULL,
                    follower_account TEXT NOT NULL,
                    follower_order_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(primary_order_id, follower_account)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_primary_order
                ON order_mappings(primary_order_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_follower_order
                ON order_mappings(follower_order_id)
            """)

            # Table for tracking processed primary orders (to prevent duplicates)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_orders (
                    primary_order_id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                )
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save_mapping(self, mapping: OrderMapping) -> None:
        """Save or update an order mapping."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO order_mappings
                (primary_order_id, follower_account, follower_order_id, symbol,
                 action, quantity, order_type, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mapping.primary_order_id,
                mapping.follower_account,
                mapping.follower_order_id,
                mapping.symbol,
                mapping.action,
                mapping.quantity,
                mapping.order_type,
                mapping.status,
                mapping.created_at,
                mapping.updated_at
            ))
            conn.commit()

    def get_follower_orders(self, primary_order_id: int) -> List[OrderMapping]:
        """Get all follower orders for a primary order."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM order_mappings
                WHERE primary_order_id = ?
            """, (primary_order_id,))

            rows = cursor.fetchall()
            return [self._row_to_mapping(row) for row in rows]

    def get_follower_order(
        self,
        primary_order_id: int,
        follower_account: str
    ) -> Optional[OrderMapping]:
        """Get a specific follower order mapping."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM order_mappings
                WHERE primary_order_id = ? AND follower_account = ?
            """, (primary_order_id, follower_account))

            row = cursor.fetchone()
            return self._row_to_mapping(row) if row else None

    def update_status(
        self,
        primary_order_id: int,
        follower_account: str,
        status: str
    ) -> None:
        """Update the status of a follower order."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE order_mappings
                SET status = ?, updated_at = ?
                WHERE primary_order_id = ? AND follower_account = ?
            """, (status, datetime.utcnow().isoformat(), primary_order_id, follower_account))
            conn.commit()

    def mark_as_processed(self, primary_order_id: int, symbol: str, action: str) -> None:
        """Mark a primary order as processed to prevent duplicate copying."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO processed_orders
                (primary_order_id, symbol, action, processed_at)
                VALUES (?, ?, ?, ?)
            """, (primary_order_id, symbol, action, datetime.utcnow().isoformat()))
            conn.commit()

    def is_processed(self, primary_order_id: int) -> bool:
        """Check if a primary order has been processed."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM processed_orders
                WHERE primary_order_id = ?
            """, (primary_order_id,))
            return cursor.fetchone() is not None

    def get_all_active_mappings(self) -> List[OrderMapping]:
        """Get all active (non-cancelled, non-rejected) order mappings."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM order_mappings
                WHERE status NOT IN ('CANCELLED', 'REJECTED')
                ORDER BY created_at DESC
            """)

            rows = cursor.fetchall()
            return [self._row_to_mapping(row) for row in rows]

    def delete_mapping(self, primary_order_id: int, follower_account: str) -> None:
        """Delete a specific order mapping."""
        with self._get_connection() as conn:
            conn.execute("""
                DELETE FROM order_mappings
                WHERE primary_order_id = ? AND follower_account = ?
            """, (primary_order_id, follower_account))
            conn.commit()

    def cleanup_old_orders(self, days: int = 30) -> int:
        """Clean up old completed/cancelled orders."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM order_mappings
                WHERE status IN ('FILLED', 'CANCELLED', 'REJECTED')
                AND datetime(updated_at) < datetime('now', '-' || ? || ' days')
            """, (days,))
            conn.commit()
            return cursor.rowcount

    @staticmethod
    def _row_to_mapping(row: sqlite3.Row) -> OrderMapping:
        """Convert a database row to an OrderMapping."""
        return OrderMapping(
            primary_order_id=row["primary_order_id"],
            follower_account=row["follower_account"],
            follower_order_id=row["follower_order_id"],
            symbol=row["symbol"],
            action=row["action"],
            quantity=row["quantity"],
            order_type=row["order_type"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    def get_stats(self) -> Dict:
        """Get statistics about stored orders."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'SUBMITTED' THEN 1 ELSE 0 END) as submitted,
                    SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) as filled,
                    SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled,
                    SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) as rejected
                FROM order_mappings
            """)
            row = cursor.fetchone()

            return {
                "total_mappings": row["total"],
                "submitted": row["submitted"],
                "filled": row["filled"],
                "cancelled": row["cancelled"],
                "rejected": row["rejected"]
            }
