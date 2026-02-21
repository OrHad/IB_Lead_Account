# Quick Start Guide

Get the IBKR Trade Copier running in 5 minutes.

## Prerequisites

1. **IB Gateway or TWS running** and accessible
   - Paper trading: Port 4002
   - API connections enabled

2. **Know your account IDs**:
   - Primary account (e.g., U1234567)
   - Follower accounts (e.g., U7654321)

## Step 1: Clone and Configure

```bash
# Clone the repository
git clone <repository-url>
cd IB_Lead_Account

# Copy environment template
cp .env.example .env

# Edit configuration (use nano, vim, or your editor)
nano .env
```

## Step 2: Minimum Required Configuration

Edit `.env` and set these **required** values:

```bash
# Your primary account ID (the one being monitored)
PRIMARY_ACCOUNT=U1234567

# Follower accounts (JSON format with multipliers)
COPY_RULES={"U7654321":{"multiplier":1.0,"enabled":true}}

# IB Gateway connection (adjust if needed)
IB_HOST=127.0.0.1
IB_PORT=4002
IB_CLIENT_ID=1

# IMPORTANT: Use DRY_RUN for testing!
DRY_RUN=true
```

**Save and close the file.**

## Step 3: Choose Your Running Method

### Option A: Docker (Recommended)

```bash
# Build and start
docker-compose up

# To run in background:
docker-compose up -d

# View logs:
docker-compose logs -f
```

### Option B: Python Virtual Environment

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the copier
python -m copier.main

# Or use the convenience script:
./run.sh
```

## Step 4: Verify It's Working

1. **Check the logs** - you should see:
   ```
   IBKR Trade Copier Starting
   Successfully connected to IB
   Trade Copier Running
   *** DRY RUN MODE - Orders will NOT be placed ***
   ```

2. **Check the health endpoint**:
   ```bash
   curl http://localhost:8080/health
   ```

   Should return `{"healthy": true, ...}`

3. **Place a test order** on your primary account (manually or via QuantConnect)

4. **Watch the logs** - you should see:
   ```
   New order detected: 12345
   [DRY RUN] Would place follower order
   ```

## Step 5: Go Live (When Ready)

**Only after thorough testing:**

1. Edit `.env`:
   ```bash
   DRY_RUN=false
   ```

2. Restart the service:
   ```bash
   # Docker
   docker-compose restart

   # Python
   # Stop with Ctrl+C, then restart:
   python -m copier.main
   ```

3. **Monitor closely** during the first live orders

## Common Issues

### "Cannot connect to IB"

- Verify IB Gateway/TWS is running
- Check `IB_PORT` is correct (4002 for paper, 4001 for live)
- Ensure API is enabled in IB Gateway settings

### "Required environment variable PRIMARY_ACCOUNT is not set"

- Check `.env` file exists in the project root
- Verify no typos in variable names
- For Docker, use `docker-compose down && docker-compose up`

### Orders not appearing

- Verify `DRY_RUN=true` is set (for testing)
- Check logs for "New order detected"
- Ensure `COPY_SYMBOLS` is empty (copies all) or contains your test symbol

## Next Steps

- Read the full [README.md](README.md) for:
  - Deployment to production (Render, VPS)
  - Advanced configuration (multipliers, filtering)
  - Monitoring and troubleshooting
  - Security best practices

## Quick Reference

### Start/Stop Commands

```bash
# Docker
docker-compose up -d        # Start in background
docker-compose logs -f      # View logs
docker-compose restart      # Restart
docker-compose down         # Stop

# Python
./run.sh                    # Start
Ctrl+C                      # Stop
```

### Check Health

```bash
curl http://localhost:8080/health | python -m json.tool
```

### View State Database

```bash
# Docker
docker-compose exec copier sqlite3 /data/copier_state.db "SELECT * FROM order_mappings LIMIT 10;"

# Local
sqlite3 /data/copier_state.db "SELECT * FROM order_mappings LIMIT 10;"
```

## Safety Checklist

Before going live:

- [ ] Tested with `DRY_RUN=true` on paper account
- [ ] Verified orders detected correctly
- [ ] Checked follower quantity calculations (multipliers)
- [ ] Reviewed logs for errors
- [ ] Health endpoint returns healthy
- [ ] Tested reconnection (stop/start IB Gateway)
- [ ] Read security section in README
- [ ] Know how to quickly stop the service

---

**Need help?** Check [README.md](README.md) for detailed documentation.
