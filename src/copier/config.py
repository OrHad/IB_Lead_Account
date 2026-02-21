"""Configuration management for the IBKR Trade Copier."""
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FollowerConfig:
    """Configuration for a follower account."""
    account_id: str
    multiplier: float = 1.0
    enabled: bool = True


@dataclass
class Config:
    """Main configuration for the trade copier."""

    # IB Connection
    ib_host: str
    ib_port: int
    ib_client_id: int
    primary_account: str

    # Follower accounts
    followers: List[FollowerConfig]

    # Safety settings
    dry_run: bool = False
    copy_symbols: Optional[List[str]] = None  # None means copy all

    # Operational settings
    reconnect_max_attempts: int = 10
    reconnect_initial_delay: float = 1.0
    reconnect_max_delay: float = 300.0
    reconnect_backoff_factor: float = 2.0

    # State persistence
    state_db_path: str = "copier_state.db"

    # Health monitoring
    health_check_enabled: bool = True
    health_check_port: int = 8080

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json or text

    # Rate limiting
    order_rate_limit: int = 50  # max orders per minute

    # Copier identification (to prevent loops)
    copier_tag: str = "COPIER_AUTO"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        # Parse follower accounts
        followers = cls._parse_followers()

        # Parse copy symbols
        copy_symbols_str = os.getenv("COPY_SYMBOLS", "")
        copy_symbols = None
        if copy_symbols_str.strip():
            copy_symbols = [s.strip() for s in copy_symbols_str.split(",") if s.strip()]

        return cls(
            # IB Connection
            ib_host=os.getenv("IB_HOST", "127.0.0.1"),
            ib_port=int(os.getenv("IB_PORT", "4002")),
            ib_client_id=int(os.getenv("IB_CLIENT_ID", "1")),
            primary_account=cls._require_env("PRIMARY_ACCOUNT"),

            # Followers
            followers=followers,

            # Safety
            dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
            copy_symbols=copy_symbols,

            # Reconnect settings
            reconnect_max_attempts=int(os.getenv("RECONNECT_MAX_ATTEMPTS", "10")),
            reconnect_initial_delay=float(os.getenv("RECONNECT_INITIAL_DELAY", "1.0")),
            reconnect_max_delay=float(os.getenv("RECONNECT_MAX_DELAY", "300.0")),
            reconnect_backoff_factor=float(os.getenv("RECONNECT_BACKOFF_FACTOR", "2.0")),

            # State
            state_db_path=os.getenv("STATE_DB_PATH", "/data/copier_state.db"),

            # Health
            health_check_enabled=os.getenv("HEALTH_CHECK_ENABLED", "true").lower() == "true",
            health_check_port=int(os.getenv("HEALTH_CHECK_PORT", "8080")),

            # Logging
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_format=os.getenv("LOG_FORMAT", "json"),

            # Rate limiting
            order_rate_limit=int(os.getenv("ORDER_RATE_LIMIT", "50")),

            # Copier tag
            copier_tag=os.getenv("COPIER_TAG", "COPIER_AUTO"),
        )

    @staticmethod
    def _require_env(key: str) -> str:
        """Get required environment variable or raise error."""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value

    @staticmethod
    def _parse_followers() -> List[FollowerConfig]:
        """Parse follower account configuration."""
        # Try COPY_RULES first (JSON with multipliers)
        copy_rules_str = os.getenv("COPY_RULES", "")
        if copy_rules_str.strip():
            try:
                copy_rules = json.loads(copy_rules_str)
                followers = []
                for account_id, rules in copy_rules.items():
                    followers.append(FollowerConfig(
                        account_id=account_id,
                        multiplier=float(rules.get("multiplier", 1.0)),
                        enabled=bool(rules.get("enabled", True))
                    ))
                return followers
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid COPY_RULES JSON: {e}")

        # Fall back to FOLLOWER_ACCOUNTS (simple list)
        follower_accounts_str = os.getenv("FOLLOWER_ACCOUNTS", "")
        if follower_accounts_str.strip():
            try:
                account_ids = json.loads(follower_accounts_str)
                return [FollowerConfig(account_id=aid) for aid in account_ids]
            except json.JSONDecodeError:
                # Try comma-separated
                account_ids = [aid.strip() for aid in follower_accounts_str.split(",") if aid.strip()]
                return [FollowerConfig(account_id=aid) for aid in account_ids]

        raise ValueError("No follower accounts configured. Set COPY_RULES or FOLLOWER_ACCOUNTS")

    def should_copy_symbol(self, symbol: str) -> bool:
        """Check if a symbol should be copied."""
        if self.copy_symbols is None:
            return True
        return symbol in self.copy_symbols

    def get_follower_quantity(self, base_quantity: float, follower_account: str) -> float:
        """Calculate follower quantity based on multiplier."""
        for follower in self.followers:
            if follower.account_id == follower_account:
                return base_quantity * follower.multiplier
        return base_quantity

    def is_follower_enabled(self, follower_account: str) -> bool:
        """Check if a follower account is enabled."""
        for follower in self.followers:
            if follower.account_id == follower_account:
                return follower.enabled
        return False
