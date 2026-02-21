"""IB connection manager with robust reconnect logic."""
import asyncio
import logging
from typing import Optional, Callable
from datetime import datetime

from ib_insync import IB, util

from .config import Config


class IBConnectionManager:
    """Manages IB connection with automatic reconnection."""

    def __init__(self, config: Config):
        """Initialize the connection manager."""
        self.config = config
        self.ib = IB()
        self.logger = logging.getLogger(__name__)
        self._reconnect_attempts = 0
        self._last_heartbeat = datetime.utcnow()
        self._connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._on_connected_callback: Optional[Callable] = None
        self._on_disconnected_callback: Optional[Callable] = None

        # Set up event handlers
        self.ib.connectedEvent += self._on_connected
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error

    def set_callbacks(
        self,
        on_connected: Optional[Callable] = None,
        on_disconnected: Optional[Callable] = None
    ):
        """Set callbacks for connection events."""
        self._on_connected_callback = on_connected
        self._on_disconnected_callback = on_disconnected

    async def connect(self) -> bool:
        """Connect to IB Gateway/TWS."""
        try:
            self.logger.info(
                "Connecting to IB",
                extra={
                    "host": self.config.ib_host,
                    "port": self.config.ib_port,
                    "client_id": self.config.ib_client_id
                }
            )

            await self.ib.connectAsync(
                host=self.config.ib_host,
                port=self.config.ib_port,
                clientId=self.config.ib_client_id,
                timeout=20
            )

            self._connected = True
            self._reconnect_attempts = 0
            self._last_heartbeat = datetime.utcnow()

            self.logger.info("Successfully connected to IB")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to IB: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect from IB."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self.ib.isConnected():
            self.ib.disconnect()

        self._connected = False
        self.logger.info("Disconnected from IB")

    def is_connected(self) -> bool:
        """Check if connected to IB."""
        return self._connected and self.ib.isConnected()

    async def ensure_connected(self) -> bool:
        """Ensure connection is active, reconnect if needed."""
        if self.is_connected():
            return True

        self.logger.warning("Connection lost, attempting to reconnect")
        return await self._reconnect_with_backoff()

    async def _reconnect_with_backoff(self) -> bool:
        """Reconnect with exponential backoff."""
        while self._reconnect_attempts < self.config.reconnect_max_attempts:
            self._reconnect_attempts += 1

            # Calculate delay with exponential backoff
            delay = min(
                self.config.reconnect_initial_delay * (
                    self.config.reconnect_backoff_factor ** (self._reconnect_attempts - 1)
                ),
                self.config.reconnect_max_delay
            )

            self.logger.info(
                f"Reconnect attempt {self._reconnect_attempts}/{self.config.reconnect_max_attempts}",
                extra={"delay_seconds": delay}
            )

            await asyncio.sleep(delay)

            if await self.connect():
                return True

        self.logger.error("Max reconnection attempts reached, giving up")
        return False

    def _on_connected(self):
        """Handle connection event."""
        self._connected = True
        self._reconnect_attempts = 0
        self._last_heartbeat = datetime.utcnow()

        self.logger.info("IB connection established")

        if self._on_connected_callback:
            try:
                self._on_connected_callback()
            except Exception as e:
                self.logger.error(f"Error in connected callback: {e}")

    def _on_disconnected(self):
        """Handle disconnection event."""
        self._connected = False

        self.logger.warning("IB connection lost")

        if self._on_disconnected_callback:
            try:
                self._on_disconnected_callback()
            except Exception as e:
                self.logger.error(f"Error in disconnected callback: {e}")

        # Start reconnection in background
        if not self._reconnect_task or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_with_backoff())

    def _on_error(self, reqId, errorCode, errorString, contract):
        """Handle IB error events."""
        # Filter out informational messages
        if errorCode in [2104, 2106, 2158]:  # Market data farm connection messages
            self.logger.debug(f"IB info: {errorCode} - {errorString}")
            return

        if errorCode >= 2000:  # Warnings
            self.logger.warning(
                f"IB warning: {errorCode} - {errorString}",
                extra={"req_id": reqId, "contract": str(contract)}
            )
        else:  # Errors
            self.logger.error(
                f"IB error: {errorCode} - {errorString}",
                extra={"req_id": reqId, "contract": str(contract)}
            )

    def update_heartbeat(self):
        """Update last heartbeat timestamp."""
        self._last_heartbeat = datetime.utcnow()

    def get_connection_health(self) -> dict:
        """Get connection health metrics."""
        return {
            "connected": self.is_connected(),
            "reconnect_attempts": self._reconnect_attempts,
            "last_heartbeat": self._last_heartbeat.isoformat(),
            "seconds_since_heartbeat": (datetime.utcnow() - self._last_heartbeat).total_seconds()
        }

    async def run_healthcheck(self):
        """Periodic health check to detect stale connections."""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                if not self.is_connected():
                    continue

                # Check for stale connection (no activity for 5 minutes)
                seconds_since_heartbeat = (datetime.utcnow() - self._last_heartbeat).total_seconds()
                if seconds_since_heartbeat > 300:
                    self.logger.warning(
                        "Connection appears stale, forcing reconnect",
                        extra={"seconds_since_heartbeat": seconds_since_heartbeat}
                    )
                    await self.disconnect()
                    await self.ensure_connected()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in health check: {e}")

    def get_ib_client(self) -> IB:
        """Get the underlying IB client."""
        return self.ib
