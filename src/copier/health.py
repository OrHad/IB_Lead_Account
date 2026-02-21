"""Health check server."""
import asyncio
import logging
from aiohttp import web
from typing import Callable


class HealthCheckServer:
    """Simple HTTP server for health checks."""

    def __init__(self, port: int, get_health_status: Callable):
        """Initialize health check server."""
        self.port = port
        self.get_health_status = get_health_status
        self.logger = logging.getLogger(__name__)
        self.app = web.Application()
        self.runner = None
        self.site = None

        # Set up routes
        self.app.router.add_get("/health", self.health_handler)
        self.app.router.add_get("/", self.health_handler)

    async def health_handler(self, request):
        """Handle health check requests."""
        try:
            status = self.get_health_status()

            if status.get("healthy", False):
                return web.json_response(status, status=200)
            else:
                return web.json_response(status, status=503)

        except Exception as e:
            self.logger.error(f"Error in health check: {e}")
            return web.json_response(
                {"healthy": False, "error": str(e)},
                status=503
            )

    async def start(self):
        """Start the health check server."""
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
            await self.site.start()
            self.logger.info(f"Health check server started on port {self.port}")
        except Exception as e:
            self.logger.error(f"Failed to start health check server: {e}")

    async def stop(self):
        """Stop the health check server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        self.logger.info("Health check server stopped")
