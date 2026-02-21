# IBKR Trade Copier

A production-ready service that automatically replicates trades from a primary Interactive Brokers account to multiple follower accounts in real-time.

## Overview

This service monitors a primary IBKR account for order activity (new orders, modifications, cancellations, fills) and automatically replicates equivalent actions to configured follower accounts. It's designed to run as an always-on background worker with robust reconnection logic, state persistence, and safety features.

### Key Features

- **Real-time Order Replication**: Monitors primary account and copies orders to followers instantly
- **Robust Connectivity**: Automatic reconnection with exponential backoff
- **State Persistence**: SQLite-based order tracking prevents duplicates across restarts
- **Loop Prevention**: Tags follower orders to prevent circular copying
- **Quantity Scaling**: Configure different position sizes per follower (multipliers)
- **Safety Features**:
  - DRY_RUN mode for testing
  - Symbol allowlist/filtering
  - Rate limiting to prevent pacing violations
- **Production Ready**:
  - Structured JSON logging
  - Health check endpoint
  - Docker deployment
  - Idempotent operations

## Architecture

```
QuantConnect/Manual Orders → Primary Account
                                    ↓
                            [IB Gateway/TWS]
                                    ↓
                            [Trade Copier Service]
                                    ↓
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
              Follower 1      Follower 2      Follower 3
```

## Prerequisites

### IBKR Setup

1. **IB Gateway or TWS** must be running and accessible
   - Paper trading: Port 4002 (Gateway) or 7497 (TWS)
   - Live trading: Port 4001 (Gateway) or 7496 (TWS)
   - Enable API connections in configuration
   - Disable read-only API mode

2. **Account Structure**:
   - One primary account (monitored)
   - One or more follower accounts
   - All accounts must be accessible via the same IB Gateway/TWS session

3. **API Configuration**:
   - Allow connections from copier host
   - Configure unique client IDs if running multiple connections

### System Requirements

- Python 3.11+
- Docker (optional, recommended for production)
- Network access to IB Gateway/TWS

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd IB_Lead_Account
```

### 2. Configure Environment

Copy the example environment file and edit with your settings:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# REQUIRED: Your primary account ID
PRIMARY_ACCOUNT=U1234567

# REQUIRED: Follower accounts with optional multipliers
COPY_RULES={"U7654321":{"multiplier":1.0,"enabled":true},"U1111111":{"multiplier":0.5,"enabled":true}}

# REQUIRED: IB Gateway connection
IB_HOST=127.0.0.1
IB_PORT=4002
IB_CLIENT_ID=1

# RECOMMENDED: Start with DRY_RUN for testing
DRY_RUN=true
```

**IMPORTANT**: Never commit `.env` to version control. It contains sensitive account information.

## Running Locally

### Option 1: Python Virtual Environment

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the copier
python -m copier.main
```

### Option 2: Docker Compose (Recommended)

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Deployment

### Deploy to Render (Background Worker)

1. **Create a New Background Worker** in Render dashboard

2. **Configure Environment Variables** in Render:
   - Go to Environment tab
   - Add each variable from `.env.example`
   - Never use the `.env` file in production

3. **Required Render Settings**:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python -m copier.main`
   - **Docker**: Optional, can use Dockerfile or native Python

4. **Network Configuration**:
   - Ensure Render worker can reach your IB Gateway
   - IB Gateway must be on a publicly accessible host, or use a VPN/tunnel
   - Consider using a VPS for IB Gateway if running from cloud

5. **Persistent Storage**:
   - Enable disk persistence in Render
   - Mount path: `/data`
   - Set `STATE_DB_PATH=/data/copier_state.db`

### Deploy to VPS with Docker

#### Option 1: Docker Compose

```bash
# SSH to your VPS
ssh user@your-vps.com

# Clone repository
git clone <repository-url>
cd IB_Lead_Account

# Create .env file (never commit this!)
nano .env
# ... paste your configuration

# Start service
docker-compose up -d

# Check logs
docker-compose logs -f copier

# Enable auto-restart
# (compose already has restart: unless-stopped)
```

#### Option 2: Systemd Service

```bash
# Create systemd service file
sudo nano /etc/systemd/system/ib-copier.service
```

```ini
[Unit]
Description=IBKR Trade Copier
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/IB_Lead_Account
EnvironmentFile=/home/your-user/IB_Lead_Account/.env
ExecStart=/home/your-user/IB_Lead_Account/venv/bin/python -m copier.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable ib-copier
sudo systemctl start ib-copier

# Check status
sudo systemctl status ib-copier

# View logs
sudo journalctl -u ib-copier -f
```

### Deploy with IB Gateway on Same Host

If running IB Gateway on the same machine as the copier:

```yaml
# docker-compose.yml
services:
  copier:
    network_mode: host
    environment:
      - IB_HOST=127.0.0.1
      - IB_PORT=4002
```

### Deploy with IB Gateway in Separate Container

You can run IB Gateway in Docker alongside the copier:

```yaml
# docker-compose.yml
services:
  ib-gateway:
    image: ghcr.io/voyz/ibc-ib-gateway:latest
    environment:
      - TWS_USERID=your-username
      - TWS_PASSWORD=your-password
      - TRADING_MODE=paper
    ports:
      - "4002:4002"
    networks:
      - ib-network

  copier:
    # ... existing config
    environment:
      - IB_HOST=ib-gateway
      - IB_PORT=4002
    depends_on:
      - ib-gateway
```

**Note**: Storing IB credentials in environment variables has security implications. Use Docker secrets or a secure vault in production.

## Configuration Reference

### Account Configuration

#### Simple Setup (Equal Copying)

```bash
FOLLOWER_ACCOUNTS=["U7654321","U1111111"]
```

All followers receive identical order sizes.

#### Advanced Setup (Scaled Copying)

```bash
COPY_RULES={"U7654321":{"multiplier":1.0,"enabled":true},"U1111111":{"multiplier":0.5,"enabled":true}}
```

- **multiplier**: Scale order quantity (0.5 = half size, 2.0 = double size)
- **enabled**: Temporarily disable a follower without removing configuration

#### Proportional Sizing (Recommended for Different Account Sizes)

**NEW FEATURE**: Automatically size orders based on buying power percentage.

```bash
USE_PROPORTIONAL_SIZING=true
```

**How it works:**
- Master account uses 10% of buying power → Followers use 10% of THEIR buying power
- Each follower automatically scales to their account size
- No manual multiplier calculation needed

**Example:**
```
Master:     $100,000 buying power → buys $10,000 of AAPL (10%)
Follower 1: $50,000 buying power  → buys $5,000 of AAPL (10%)
Follower 2: $200,000 buying power → buys $20,000 of AAPL (10%)
```

**Benefits:**
- Perfect for accounts of different sizes
- Automatically maintains proportional exposure
- No need to calculate multipliers manually
- Adapts as account values change

**When to use:**
- ✅ Follower accounts have different sizes than master
- ✅ You want same % allocation across all accounts
- ✅ Account sizes change over time

**When to use multipliers instead:**
- You want specific fixed ratios (e.g., always half size)
- All accounts have similar sizes
- `USE_PROPORTIONAL_SIZING=false` (uses COPY_RULES multipliers)

### Safety Features

#### DRY_RUN Mode

```bash
DRY_RUN=true
```

Logs intended orders without placing them. Use this for testing configuration.

#### Symbol Filtering

```bash
# Only copy specific symbols
COPY_SYMBOLS=AAPL,MSFT,GOOGL

# Copy all symbols (default)
COPY_SYMBOLS=
```

### Connection Settings

```bash
# IB Gateway/TWS host
IB_HOST=127.0.0.1

# Port (paper: 4002, live: 4001 for Gateway)
IB_PORT=4002

# Unique client ID (1-32)
IB_CLIENT_ID=1

# Reconnection settings
RECONNECT_MAX_ATTEMPTS=10
RECONNECT_INITIAL_DELAY=1.0
RECONNECT_MAX_DELAY=300.0
```

### Logging

```bash
# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO

# Format: json (production) or text (development)
LOG_FORMAT=json
```

## Monitoring

### Health Check Endpoint

The service exposes a health check at `http://localhost:8080/health`:

```bash
curl http://localhost:8080/health
```

Response:

```json
{
  "healthy": true,
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "primary_account": "U1234567",
  "follower_count": 2,
  "dry_run": false,
  "connection": {
    "connected": true,
    "reconnect_attempts": 0,
    "last_heartbeat": "2024-01-15T10:30:00Z",
    "seconds_since_heartbeat": 15
  },
  "stats": {
    "total_mappings": 150,
    "submitted": 10,
    "filled": 135,
    "cancelled": 5,
    "rejected": 0
  }
}
```

### Logs

Structured JSON logs (when `LOG_FORMAT=json`):

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "logger": "copier.copy_engine",
  "message": "Placed follower order 123456",
  "primary_order_id": 999,
  "follower_account": "U7654321",
  "symbol": "AAPL",
  "action": "BUY",
  "quantity": 100
}
```

View logs:

```bash
# Docker Compose
docker-compose logs -f copier

# Systemd
sudo journalctl -u ib-copier -f

# Direct Python
python -m copier.main 2>&1 | tee copier.log
```

### Monitoring Checklist

- [ ] Health endpoint returns `healthy: true`
- [ ] Connection shows `connected: true`
- [ ] Heartbeat timestamp updates regularly
- [ ] No repeated reconnection attempts
- [ ] Order mappings increase with trading activity
- [ ] No rejected orders (or investigate reasons)

## How It Works

### Order Flow

1. **Detection**: Primary account places order (via QuantConnect or manually)
2. **Event**: IB Gateway notifies copier of new order event
3. **Validation**:
   - Check if symbol is in allowlist
   - Verify order not already processed (idempotency)
   - Skip copier-tagged orders (loop prevention)
4. **Replication**: For each enabled follower:
   - Calculate scaled quantity (multiplier)
   - Create equivalent order (same type, prices, TIF)
   - Tag with copier identifier
   - Apply rate limiting
   - Place order on follower account
5. **Persistence**: Save primary ↔ follower mapping to SQLite
6. **Updates**: Monitor for modifications/cancellations and replicate

### Loop Prevention

Follower orders are tagged with `orderRef = "COPIER_AUTO:{primary_order_id}"`. The listener skips any orders containing this tag, preventing:

- Follower orders from being copied back to primary
- Follower orders from being copied to other followers

### Idempotency

The state store tracks which primary orders have been processed. On restart:

1. Loads existing open orders from IB
2. Rebuilds state from SQLite
3. Prevents re-copying of orders that were already processed

### Reconnection Logic

On disconnect:

1. Log disconnection event
2. Wait with exponential backoff (1s → 2s → 4s → ... → 300s max)
3. Attempt reconnection (up to 10 attempts)
4. On successful reconnect:
   - Reload open orders
   - Rebuild listener state
   - Resume monitoring

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to IB Gateway

**Solutions**:
- Verify IB Gateway/TWS is running
- Check `IB_HOST` and `IB_PORT` are correct
- Ensure API connections are enabled in IB Gateway settings
- Verify firewall allows connection
- Check client ID is not already in use

### Orders Not Copying

**Problem**: Orders on primary not appearing on followers

**Checks**:
- Verify `PRIMARY_ACCOUNT` matches the monitored account
- Check `COPY_SYMBOLS` filter (empty = copy all)
- Ensure `DRY_RUN=false` (if in dry run, orders are logged but not placed)
- Review logs for rejection reasons
- Verify follower accounts are `"enabled": true`

### Duplicate Orders

**Problem**: Same order copied multiple times

**Cause**: State database lost or corrupted

**Solutions**:
- Ensure `STATE_DB_PATH` points to persistent storage
- In Docker, verify volume is mounted correctly
- Check database file permissions
- Review logs for SQLite errors

### Rate Limiting / Pacing Violations

**Problem**: IB rejects orders due to pacing violations

**Solution**: Reduce `ORDER_RATE_LIMIT`:

```bash
ORDER_RATE_LIMIT=20  # Reduce from default 50
```

### High Memory Usage

**Problem**: Service memory grows over time

**Solution**: Implement periodic cleanup:

```python
# In state_store.py, already implemented:
state_store.cleanup_old_orders(days=30)  # Remove old completed orders
```

Schedule this in a cron job or add to the main loop.

## Security Best Practices

### Secrets Management

**DO**:
- Use environment variables for all secrets
- Store secrets in GitHub Secrets (GitHub Actions)
- Store secrets in Render Environment Variables (Render)
- Use `.env` file on VPS (never commit)
- Use Docker secrets or Vault in production

**DON'T**:
- Commit `.env` to git
- Hardcode account IDs or credentials
- Print secrets in logs
- Share `.env` files

### Network Security

- Run IB Gateway on private network when possible
- Use VPN/tunnel for cloud deployments
- Restrict health endpoint access (firewall, auth)
- Monitor for unauthorized access attempts

### Operational Security

- Start with `DRY_RUN=true` to verify configuration
- Test with paper trading accounts first
- Use `COPY_SYMBOLS` to limit scope initially
- Monitor logs closely during initial deployment
- Set up alerts for errors and disconnections

## Advanced Topics

### Multiple Primary Accounts

To monitor multiple primary accounts, run multiple copier instances with different:

- `IB_CLIENT_ID` (must be unique)
- `PRIMARY_ACCOUNT`
- `STATE_DB_PATH` (separate databases)
- `HEALTH_CHECK_PORT` (if on same host)

### Position Reconciliation

The copier focuses on order copying, not position tracking. For position reconciliation:

```python
# Optional enhancement (not implemented in MVP)
# Check positions periodically and alert on drift
primary_positions = ib.positions(primary_account)
follower_positions = ib.positions(follower_account)
# Compare and alert on discrepancies
```

### Custom Order Filtering

Extend `Config.should_copy_symbol()` for advanced filtering:

```python
def should_copy_symbol(self, symbol: str, order_type: str = None) -> bool:
    # Example: Only copy market orders for certain symbols
    if order_type == "MKT" and symbol in ["AAPL", "MSFT"]:
        return True
    return self.copy_symbols is None or symbol in self.copy_symbols
```

### Multi-Region Deployment

For global redundancy, deploy multiple copier instances in different regions with:

- Shared state database (PostgreSQL, MySQL)
- Leader election (Redis, etcd)
- Active-passive failover

This requires modifications beyond the MVP scope.

## Project Structure

```
IB_Lead_Account/
├── src/
│   └── copier/
│       ├── __init__.py
│       ├── main.py              # Main orchestrator
│       ├── config.py            # Configuration management
│       ├── state_store.py       # SQLite state persistence
│       ├── ib_connection.py     # Connection manager
│       ├── ib_listener.py       # Order event listener
│       ├── copy_engine.py       # Order replication logic
│       ├── health.py            # Health check server
│       └── logging_config.py    # Logging setup
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Contributing

Contributions are welcome! Please ensure:

- Code follows existing style
- Add tests for new features
- Update documentation
- No secrets in commits

## Support

For issues, questions, or feature requests, please open a GitHub issue.

## License

[Your License Here]

## Disclaimer

This software is provided as-is. Trading involves risk. Test thoroughly with paper trading before using with live accounts. The authors are not responsible for any financial losses.
