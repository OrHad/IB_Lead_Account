# IBKR Trade Copier - Project Overview

## What Was Built

A production-ready, always-on service that automatically replicates trades from a primary Interactive Brokers account to multiple follower accounts in real-time.

## Project Structure

```
IB_Lead_Account/
├── src/copier/                      # Main application package
│   ├── __init__.py                  # Package initialization
│   ├── __main__.py                  # Entry point for module execution
│   ├── main.py                      # Main orchestrator with signal handling
│   ├── config.py                    # Configuration management & validation
│   ├── state_store.py               # SQLite-based state persistence
│   ├── ib_connection.py             # IB connection manager with reconnect
│   ├── ib_listener.py               # Order event listener for primary account
│   ├── copy_engine.py               # Core order replication logic
│   ├── health.py                    # HTTP health check server
│   └── logging_config.py            # Structured logging setup
│
├── Dockerfile                       # Docker image definition
├── docker-compose.yml               # Docker Compose orchestration
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment template (safe to commit)
├── .gitignore                       # Git ignore rules
│
├── README.md                        # Comprehensive documentation
├── QUICKSTART.md                    # 5-minute setup guide
├── PROJECT_OVERVIEW.md              # This file
│
├── run.sh                           # Convenience startup script
└── test_config.py                   # Configuration validation tool
```

## Core Components

### 1. Configuration Management (`config.py`)
- Environment-based configuration (12-factor app)
- Support for simple and advanced follower rules
- Built-in validation
- Safe defaults

### 2. State Store (`state_store.py`)
- SQLite database for order mappings
- Tracks primary_order_id → follower_order_id relationships
- Idempotency (prevents duplicate copying on restart)
- Automatic schema initialization
- Statistics and cleanup utilities

### 3. Connection Manager (`ib_connection.py`)
- Manages IB Gateway/TWS connection
- Exponential backoff reconnection logic
- Configurable retry attempts and delays
- Stale connection detection
- Health monitoring

### 4. Order Listener (`ib_listener.py`)
- Monitors primary account for order events
- Detects new orders, modifications, cancellations, fills
- Loop prevention (ignores copier-tagged orders)
- Symbol filtering
- State rebuild on reconnect

### 5. Copy Engine (`copy_engine.py`)
- Replicates orders to follower accounts
- Supports MKT, LMT, STP, STP LMT order types
- Quantity scaling (multipliers)
- Rate limiting (token bucket algorithm)
- DRY_RUN mode for testing
- Handles order modifications and cancellations

### 6. Main Orchestrator (`main.py`)
- Coordinates all components
- Signal handling (SIGTERM, SIGINT)
- Heartbeat monitoring
- Health status aggregation
- Graceful shutdown

### 7. Health Check Server (`health.py`)
- HTTP endpoint for monitoring
- Returns connection status, uptime, statistics
- Used by Docker healthcheck
- Production monitoring integration

## Key Features Implemented

### Safety Features
✓ DRY_RUN mode - test without placing orders
✓ Symbol allowlist - limit which symbols to copy
✓ Loop prevention - tagged orders prevent circular copying
✓ Rate limiting - prevent IBKR pacing violations
✓ Idempotency - no duplicate orders on restart

### Reliability Features
✓ Automatic reconnection with exponential backoff
✓ State persistence (SQLite)
✓ Stale connection detection
✓ Graceful shutdown
✓ Error handling with detailed logging

### Production Features
✓ Structured JSON logging
✓ Health check endpoint
✓ Docker deployment ready
✓ Environment-based secrets
✓ Comprehensive documentation

### Advanced Features
✓ Quantity scaling (multipliers per follower)
✓ Enable/disable followers without removing config
✓ Multiple order type support
✓ Execution tracking
✓ Statistics and monitoring

## Deployment Options

### 1. Local Development
```bash
python -m copier.main
# or
./run.sh
```

### 2. Docker Compose
```bash
docker-compose up -d
```

### 3. Render (Cloud Background Worker)
- Set environment variables in dashboard
- Deploy from GitHub
- Automatic scaling and health checks

### 4. VPS with Docker
```bash
docker-compose up -d
# or systemd service
```

## Testing Strategy

### 1. Configuration Validation
```bash
./test_config.py
```

### 2. DRY_RUN Testing
```bash
DRY_RUN=true docker-compose up
```

### 3. Paper Trading
- Use paper account IDs
- Test all order types
- Verify quantity scaling

### 4. Production Rollout
- Start with DRY_RUN=false
- Monitor closely
- Use symbol filtering initially

## Security Considerations

### Implemented
✓ No secrets in code
✓ Environment-based configuration
✓ .env excluded from git
✓ Account IDs masked in test output
✓ Secrets never logged

### Recommended
- Use Docker secrets or Vault for production
- Restrict network access to IB Gateway
- Enable firewall rules
- Monitor health endpoint access
- Rotate credentials regularly

## Monitoring & Observability

### Logs
- Structured JSON format (default)
- Timestamp, level, logger, message
- Extra context fields
- Human-readable text mode available

### Health Checks
- HTTP endpoint: `GET /health`
- Connection status
- Uptime tracking
- Order statistics
- Heartbeat monitoring

### Metrics Tracked
- Total order mappings
- Orders by status (submitted, filled, cancelled, rejected)
- Reconnection attempts
- Seconds since last heartbeat

## Configuration Examples

### Simple Setup (One Follower, Equal Size)
```bash
PRIMARY_ACCOUNT=U1234567
FOLLOWER_ACCOUNTS=["U7654321"]
DRY_RUN=true
```

### Advanced Setup (Multiple Followers, Scaled)
```bash
PRIMARY_ACCOUNT=U1234567
COPY_RULES={"U7654321":{"multiplier":1.0},"U1111111":{"multiplier":0.5}}
COPY_SYMBOLS=AAPL,MSFT,GOOGL
DRY_RUN=false
```

### Production Setup
```bash
PRIMARY_ACCOUNT=U1234567
COPY_RULES={"U7654321":{"multiplier":1.0}}
IB_HOST=10.0.1.5
IB_PORT=4001
LOG_LEVEL=INFO
LOG_FORMAT=json
HEALTH_CHECK_ENABLED=true
STATE_DB_PATH=/data/copier_state.db
ORDER_RATE_LIMIT=30
```

## Getting Started

1. **Quick Start**: Read `QUICKSTART.md` for 5-minute setup
2. **Full Documentation**: Read `README.md` for comprehensive guide
3. **Test Configuration**: Run `./test_config.py` to validate setup
4. **Start Service**: Use Docker Compose or Python directly

## Future Enhancements (Not in MVP)

Potential features for future versions:
- Position reconciliation
- Multi-region deployment with leader election
- Web UI for monitoring
- Advanced filtering rules (by order type, time, etc.)
- Partial fill handling improvements
- PostgreSQL support for state store
- Prometheus metrics export
- Alert integration (Slack, PagerDuty)

## Support & Documentation

- **README.md**: Full documentation with deployment guides
- **QUICKSTART.md**: Fast setup for immediate use
- **test_config.py**: Configuration validation
- **.env.example**: All available configuration options

## Technical Stack

- **Language**: Python 3.11+
- **IBKR API**: ib-insync (0.9.86)
- **Async**: asyncio, aiohttp
- **State**: SQLite
- **Deployment**: Docker, Docker Compose
- **Logging**: JSON structured logs

## Architecture Decisions

### Why ib-insync over ibapi?
- Simpler async API
- Built-in event handling
- Automatic reconnection helpers
- Better developer experience

### Why SQLite?
- Zero configuration
- File-based (easy backups)
- Sufficient for order mapping use case
- Can migrate to PostgreSQL later if needed

### Why JSON logging?
- Structured data for log aggregation
- Easy parsing by monitoring tools
- Production standard

### Why Docker?
- Consistent environment
- Easy deployment
- Health checks built-in
- Portable across platforms

## License & Disclaimer

See README.md for license information.

**Trading involves risk. Test thoroughly before using with live accounts.**
