"""Main orchestrator for the IBKR Trade Copier."""
import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

from ib_insync import util

from .config import Config
from .state_store import StateStore
from .ib_connection import IBConnectionManager
from .ib_listener import OrderListener
from .copy_engine import CopyEngine
from .health import HealthCheckServer
from .logging_config import setup_logging


class TradeCopier:
    """Main trade copier orchestrator."""

    def __init__(self):
        """Initialize the trade copier."""
        self.logger = None
        self.config: Optional[Config] = None
        self.state_store: Optional[StateStore] = None
        self.connection_manager: Optional[IBConnectionManager] = None
        self.order_listener: Optional[OrderListener] = None
        self.copy_engine: Optional[CopyEngine] = None
        self.health_server: Optional[HealthCheckServer] = None
        self.running = False
        self.start_time = datetime.utcnow()

    async def initialize(self):
        """Initialize all components."""
        try:
            # Load configuration
            self.config = Config.from_env()

            # Set up logging
            setup_logging(self.config.log_level, self.config.log_format)
            self.logger = logging.getLogger(__name__)

            self.logger.info("=" * 60)
            self.logger.info("IBKR Trade Copier Starting")
            self.logger.info("=" * 60)
            self.logger.info(
                "Configuration loaded",
                extra={
                    "primary_account": self.config.primary_account,
                    "follower_count": len(self.config.followers),
                    "dry_run": self.config.dry_run,
                    "copy_symbols": self.config.copy_symbols or "ALL"
                }
            )

            # Initialize state store
            self.logger.info(f"Initializing state store: {self.config.state_db_path}")
            self.state_store = StateStore(self.config.state_db_path)

            # Log state store stats
            stats = self.state_store.get_stats()
            self.logger.info("State store initialized", extra=stats)

            # Initialize connection manager
            self.logger.info("Initializing IB connection manager")
            self.connection_manager = IBConnectionManager(self.config)

            # Initialize copy engine
            self.logger.info("Initializing copy engine")
            self.copy_engine = CopyEngine(
                self.connection_manager.get_ib_client(),
                self.config,
                self.state_store
            )

            # Initialize order listener with copy engine callbacks
            self.logger.info("Initializing order listener")
            self.order_listener = OrderListener(
                self.connection_manager.get_ib_client(),
                self.config,
                on_new_order=lambda trade: asyncio.create_task(self.copy_engine.copy_new_order(trade)),
                on_order_modified=lambda trade: asyncio.create_task(self.copy_engine.handle_order_modified(trade)),
                on_order_cancelled=lambda trade: asyncio.create_task(self.copy_engine.handle_order_cancelled(trade)),
                on_order_filled=lambda trade: asyncio.create_task(self.copy_engine.handle_order_filled(trade))
            )

            # Set connection callbacks
            self.connection_manager.set_callbacks(
                on_connected=self._on_connected,
                on_disconnected=self._on_disconnected
            )

            # Initialize health check server
            if self.config.health_check_enabled:
                self.logger.info(f"Initializing health check server on port {self.config.health_check_port}")
                self.health_server = HealthCheckServer(
                    self.config.health_check_port,
                    self.get_health_status
                )

            self.logger.info("Initialization complete")

        except Exception as e:
            self.logger.error(f"Initialization failed: {e}", exc_info=True)
            raise

    async def start(self):
        """Start the trade copier."""
        try:
            self.running = True

            # Connect to IB
            self.logger.info("Connecting to IB Gateway/TWS")
            if not await self.connection_manager.connect():
                raise Exception("Failed to connect to IB")

            # Start order listener
            self.order_listener.start()

            # Start health check server
            if self.health_server:
                await self.health_server.start()

            # Start health check task
            health_check_task = asyncio.create_task(
                self.connection_manager.run_healthcheck()
            )

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._run_heartbeat())

            self.logger.info("=" * 60)
            self.logger.info("Trade Copier Running")
            self.logger.info("=" * 60)

            if self.config.dry_run:
                self.logger.warning("*** DRY RUN MODE - Orders will NOT be placed ***")

            # Run event loop
            await asyncio.gather(
                health_check_task,
                heartbeat_task,
                return_exceptions=True
            )

        except asyncio.CancelledError:
            self.logger.info("Trade copier shutting down")
        except Exception as e:
            self.logger.error(f"Error in trade copier: {e}", exc_info=True)
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the trade copier."""
        if not self.running:
            return

        self.running = False
        self.logger.info("Stopping trade copier")

        # Stop order listener
        if self.order_listener:
            self.order_listener.stop()

        # Stop health check server
        if self.health_server:
            await self.health_server.stop()

        # Disconnect from IB
        if self.connection_manager:
            await self.connection_manager.disconnect()

        self.logger.info("Trade copier stopped")

    def _on_connected(self):
        """Handle connection established."""
        self.logger.info("IB connection established, rebuilding state")
        if self.order_listener:
            self.order_listener.rebuild_state_on_reconnect()

    def _on_disconnected(self):
        """Handle disconnection."""
        self.logger.warning("IB connection lost, will attempt to reconnect")

    async def _run_heartbeat(self):
        """Periodic heartbeat log."""
        while self.running:
            try:
                await asyncio.sleep(60)  # Every minute

                if self.connection_manager and self.connection_manager.is_connected():
                    self.connection_manager.update_heartbeat()

                    # Log heartbeat with stats
                    stats = self.state_store.get_stats() if self.state_store else {}
                    uptime = (datetime.utcnow() - self.start_time).total_seconds()

                    self.logger.info(
                        "Heartbeat",
                        extra={
                            "uptime_seconds": uptime,
                            "connected": True,
                            **stats
                        }
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in heartbeat: {e}")

    def get_health_status(self) -> dict:
        """Get current health status."""
        connection_health = self.connection_manager.get_connection_health() if self.connection_manager else {}
        stats = self.state_store.get_stats() if self.state_store else {}

        is_healthy = (
            self.running and
            connection_health.get("connected", False)
        )

        return {
            "healthy": is_healthy,
            "version": "1.0.0",
            "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
            "primary_account": self.config.primary_account if self.config else None,
            "follower_count": len(self.config.followers) if self.config else 0,
            "dry_run": self.config.dry_run if self.config else False,
            "connection": connection_health,
            "stats": stats
        }


async def async_main():
    """Async main entry point."""
    copier = TradeCopier()

    # Set up signal handlers
    loop = asyncio.get_running_loop()

    def handle_signal(sig):
        """Handle shutdown signals."""
        logging.getLogger(__name__).info(f"Received signal {sig}, shutting down")
        asyncio.create_task(copier.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    try:
        await copier.initialize()
        await copier.start()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Keyboard interrupt received")
    except Exception as e:
        logging.getLogger(__name__).error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point."""
    # Enable asyncio debug mode in development
    # asyncio.get_event_loop().set_debug(True)

    # Use ib_insync's event loop integration
    util.startLoop()
    try:
        asyncio.run(async_main())
    finally:
        util.stopLoop()


if __name__ == "__main__":
    main()
