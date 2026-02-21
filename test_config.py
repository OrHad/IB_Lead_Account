#!/usr/bin/env python3
"""Configuration validation script - run before starting the copier."""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def test_config():
    """Test configuration loading and validation."""
    print("=" * 60)
    print("IBKR Trade Copier - Configuration Validator")
    print("=" * 60)
    print()

    # Try to load .env file
    env_file = Path(".env")
    if env_file.exists():
        print("✓ Found .env file")
        try:
            from dotenv import load_dotenv
            load_dotenv()
            print("✓ Loaded environment variables from .env")
        except ImportError:
            print("⚠ python-dotenv not installed, using system environment")
    else:
        print("⚠ No .env file found, using system environment")

    print()
    print("Configuration Validation:")
    print("-" * 60)

    errors = []
    warnings = []

    # Test required variables
    required_vars = {
        "PRIMARY_ACCOUNT": "Primary account ID",
        "IB_HOST": "IB Gateway host",
        "IB_PORT": "IB Gateway port",
    }

    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            # Mask account IDs for security
            display_value = value if var != "PRIMARY_ACCOUNT" else f"{value[:2]}****{value[-2:]}"
            print(f"✓ {description}: {display_value}")
        else:
            errors.append(f"✗ Missing required variable: {var}")
            print(f"✗ {description}: NOT SET")

    # Test follower configuration
    copy_rules = os.getenv("COPY_RULES")
    follower_accounts = os.getenv("FOLLOWER_ACCOUNTS")

    if copy_rules:
        print(f"✓ Follower configuration: COPY_RULES set")
        try:
            import json
            rules = json.loads(copy_rules)
            print(f"  - {len(rules)} follower account(s) configured")
            for account_id, config in rules.items():
                multiplier = config.get("multiplier", 1.0)
                enabled = config.get("enabled", True)
                status = "ENABLED" if enabled else "DISABLED"
                print(f"  - {account_id[:2]}****{account_id[-2:]}: {multiplier}x ({status})")
        except json.JSONDecodeError as e:
            errors.append(f"✗ Invalid COPY_RULES JSON: {e}")
    elif follower_accounts:
        print(f"✓ Follower configuration: FOLLOWER_ACCOUNTS set")
        try:
            import json
            accounts = json.loads(follower_accounts)
            print(f"  - {len(accounts)} follower account(s) configured")
        except json.JSONDecodeError:
            # Try comma-separated
            accounts = [a.strip() for a in follower_accounts.split(",")]
            print(f"  - {len(accounts)} follower account(s) configured")
    else:
        errors.append("✗ No follower accounts configured (COPY_RULES or FOLLOWER_ACCOUNTS)")

    # Test optional but important settings
    dry_run = os.getenv("DRY_RUN", "false").lower()
    if dry_run == "true":
        print("⚠ DRY_RUN mode: Orders will NOT be placed (safe for testing)")
    else:
        warnings.append("⚠ DRY_RUN=false: Orders WILL be placed on follower accounts!")
        print("⚠ DRY_RUN=false: Orders WILL be placed!")

    copy_symbols = os.getenv("COPY_SYMBOLS", "")
    if copy_symbols:
        symbols = [s.strip() for s in copy_symbols.split(",")]
        print(f"✓ Symbol filter: Only copying {len(symbols)} symbol(s): {', '.join(symbols)}")
    else:
        print("✓ Symbol filter: Copying ALL symbols")

    # Test logging
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_format = os.getenv("LOG_FORMAT", "json")
    print(f"✓ Logging: {log_level} level, {log_format} format")

    # Test state persistence
    state_db_path = os.getenv("STATE_DB_PATH", "/data/copier_state.db")
    state_dir = Path(state_db_path).parent
    if state_dir.exists():
        print(f"✓ State database directory exists: {state_dir}")
    else:
        warnings.append(f"⚠ State database directory does not exist: {state_dir}")
        print(f"⚠ State database directory does not exist: {state_dir}")
        print(f"  (Will be created on first run)")

    # Test health check
    health_enabled = os.getenv("HEALTH_CHECK_ENABLED", "true").lower()
    if health_enabled == "true":
        health_port = os.getenv("HEALTH_CHECK_PORT", "8080")
        print(f"✓ Health check enabled on port {health_port}")
    else:
        print("⚠ Health check disabled")

    print()
    print("=" * 60)

    # Try to actually load the config
    print("\nAttempting to load configuration module...")
    try:
        from copier.config import Config
        config = Config.from_env()
        print("✓ Configuration loaded successfully!")
        print()
        print(f"  Primary Account: {config.primary_account[:2]}****{config.primary_account[-2:]}")
        print(f"  Follower Count: {len(config.followers)}")
        print(f"  DRY_RUN: {config.dry_run}")
        print(f"  IB Connection: {config.ib_host}:{config.ib_port} (client {config.ib_client_id})")
    except Exception as e:
        errors.append(f"✗ Failed to load configuration: {e}")
        print(f"✗ Failed to load configuration: {e}")

    print()
    print("=" * 60)
    print("Summary:")
    print("-" * 60)

    if errors:
        print(f"\n✗ {len(errors)} ERROR(S) - FIX BEFORE RUNNING:")
        for error in errors:
            print(f"  {error}")

    if warnings:
        print(f"\n⚠ {len(warnings)} WARNING(S):")
        for warning in warnings:
            print(f"  {warning}")

    if not errors and not warnings:
        print("\n✓ All checks passed! Configuration looks good.")
        print("\nReady to start the copier:")
        print("  Docker:  docker-compose up")
        print("  Python:  python -m copier.main")
    elif not errors:
        print("\n✓ Configuration is valid (warnings are informational)")
        print("\nReady to start the copier:")
        print("  Docker:  docker-compose up")
        print("  Python:  python -m copier.main")
    else:
        print("\n✗ Please fix the errors above before starting the copier.")
        return 1

    print()
    return 0


if __name__ == "__main__":
    sys.exit(test_config())
