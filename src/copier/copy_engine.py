"""Copy engine for replicating orders to follower accounts."""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from ib_insync import IB, Order, Trade, MarketOrder, LimitOrder, StopOrder, StopLimitOrder

from .config import Config
from .state_store import StateStore, OrderMapping


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, max_per_minute: int):
        """Initialize rate limiter."""
        self.max_per_minute = max_per_minute
        self.tokens = max_per_minute
        self.last_update = datetime.utcnow()
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Acquire a token, waiting if necessary."""
        async with self.lock:
            now = datetime.utcnow()
            elapsed = (now - self.last_update).total_seconds()

            # Refill tokens based on elapsed time
            self.tokens = min(
                self.max_per_minute,
                self.tokens + (elapsed * self.max_per_minute / 60.0)
            )
            self.last_update = now

            # If no tokens available, wait
            if self.tokens < 1:
                wait_time = (1 - self.tokens) * 60.0 / self.max_per_minute
                await asyncio.sleep(wait_time)
                self.tokens = 1

            self.tokens -= 1


class CopyEngine:
    """Engine for copying orders from primary to follower accounts."""

    def __init__(self, ib: IB, config: Config, state_store: StateStore):
        """Initialize the copy engine."""
        self.ib = ib
        self.config = config
        self.state_store = state_store
        self.logger = logging.getLogger(__name__)
        self.rate_limiter = RateLimiter(config.order_rate_limit)

    async def copy_new_order(self, trade: Trade):
        """Copy a new order to all follower accounts."""
        try:
            primary_order = trade.order
            primary_order_id = primary_order.orderId
            contract = trade.contract

            self.logger.info(
                f"Copying new order {primary_order_id}",
                extra={
                    "symbol": contract.symbol,
                    "action": primary_order.action,
                    "quantity": primary_order.totalQuantity,
                    "order_type": primary_order.orderType
                }
            )

            # Check if already processed (idempotency)
            if self.state_store.is_processed(primary_order_id):
                self.logger.warning(
                    f"Order {primary_order_id} already processed, skipping",
                    extra={"symbol": contract.symbol}
                )
                return

            # Mark as processed
            self.state_store.mark_as_processed(
                primary_order_id,
                contract.symbol,
                primary_order.action
            )

            # Copy to each follower
            for follower_config in self.config.followers:
                if not follower_config.enabled:
                    self.logger.debug(f"Follower {follower_config.account_id} is disabled, skipping")
                    continue

                try:
                    await self._copy_to_follower(trade, follower_config.account_id)
                except Exception as e:
                    self.logger.error(
                        f"Failed to copy order to follower {follower_config.account_id}: {e}",
                        exc_info=True
                    )
                    # Continue with other followers

        except Exception as e:
            self.logger.error(f"Error copying new order: {e}", exc_info=True)

    async def _copy_to_follower(self, trade: Trade, follower_account: str):
        """Copy an order to a specific follower account."""
        primary_order = trade.order
        primary_order_id = primary_order.orderId
        contract = trade.contract

        # Calculate follower quantity
        follower_quantity = self.config.get_follower_quantity(
            primary_order.totalQuantity,
            follower_account
        )

        # Create follower order
        follower_order = self._create_follower_order(primary_order, follower_quantity)

        # Set account
        follower_order.account = follower_account

        # Tag with copier identifier to prevent loops
        follower_order.orderRef = f"{self.config.copier_tag}:{primary_order_id}"

        # DRY RUN mode
        if self.config.dry_run:
            self.logger.info(
                "[DRY RUN] Would place follower order",
                extra={
                    "follower_account": follower_account,
                    "symbol": contract.symbol,
                    "action": follower_order.action,
                    "quantity": follower_order.totalQuantity,
                    "order_type": follower_order.orderType
                }
            )
            return

        # Rate limiting
        await self.rate_limiter.acquire()

        # Place order
        try:
            follower_trade = self.ib.placeOrder(contract, follower_order)

            # Wait a bit for order to be acknowledged
            await asyncio.sleep(0.5)

            follower_order_id = follower_order.orderId

            self.logger.info(
                f"Placed follower order {follower_order_id}",
                extra={
                    "primary_order_id": primary_order_id,
                    "follower_account": follower_account,
                    "symbol": contract.symbol,
                    "action": follower_order.action,
                    "quantity": follower_order.totalQuantity
                }
            )

            # Save mapping
            mapping = OrderMapping(
                primary_order_id=primary_order_id,
                follower_account=follower_account,
                follower_order_id=follower_order_id,
                symbol=contract.symbol,
                action=follower_order.action,
                quantity=follower_order.totalQuantity,
                order_type=follower_order.orderType,
                status="SUBMITTED",
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat()
            )
            self.state_store.save_mapping(mapping)

        except Exception as e:
            self.logger.error(
                f"Failed to place order on follower {follower_account}: {e}",
                exc_info=True
            )
            raise

    def _create_follower_order(self, primary_order: Order, quantity: float) -> Order:
        """Create a follower order based on primary order."""
        # Map order type
        order_type = primary_order.orderType.upper()

        if order_type == "MKT":
            follower_order = MarketOrder(
                action=primary_order.action,
                totalQuantity=quantity
            )

        elif order_type == "LMT":
            follower_order = LimitOrder(
                action=primary_order.action,
                totalQuantity=quantity,
                lmtPrice=primary_order.lmtPrice
            )

        elif order_type == "STP":
            follower_order = StopOrder(
                action=primary_order.action,
                totalQuantity=quantity,
                stopPrice=primary_order.auxPrice
            )

        elif order_type == "STP LMT":
            follower_order = StopLimitOrder(
                action=primary_order.action,
                totalQuantity=quantity,
                lmtPrice=primary_order.lmtPrice,
                stopPrice=primary_order.auxPrice
            )

        else:
            # Default to market order for unsupported types
            self.logger.warning(f"Unsupported order type {order_type}, using MKT")
            follower_order = MarketOrder(
                action=primary_order.action,
                totalQuantity=quantity
            )

        # Copy common attributes
        follower_order.tif = primary_order.tif
        follower_order.outsideRth = primary_order.outsideRth
        follower_order.hidden = primary_order.hidden
        follower_order.orderType = primary_order.orderType

        return follower_order

    async def handle_order_modified(self, trade: Trade):
        """Handle modification of a primary order."""
        try:
            primary_order = trade.order
            primary_order_id = primary_order.orderId
            contract = trade.contract

            self.logger.info(
                f"Handling order modification {primary_order_id}",
                extra={"symbol": contract.symbol}
            )

            # Get existing follower orders
            follower_mappings = self.state_store.get_follower_orders(primary_order_id)

            if not follower_mappings:
                self.logger.warning(f"No follower orders found for {primary_order_id}")
                return

            # Cancel and replace follower orders
            for mapping in follower_mappings:
                if not self.config.is_follower_enabled(mapping.follower_account):
                    continue

                try:
                    await self._modify_follower_order(trade, mapping)
                except Exception as e:
                    self.logger.error(
                        f"Failed to modify follower order for {mapping.follower_account}: {e}",
                        exc_info=True
                    )

        except Exception as e:
            self.logger.error(f"Error handling order modification: {e}", exc_info=True)

    async def _modify_follower_order(self, trade: Trade, mapping: OrderMapping):
        """Modify a follower order (cancel and replace)."""
        primary_order = trade.order
        contract = trade.contract

        # Calculate new quantity
        new_quantity = self.config.get_follower_quantity(
            primary_order.totalQuantity,
            mapping.follower_account
        )

        # Create new order
        new_order = self._create_follower_order(primary_order, new_quantity)
        new_order.account = mapping.follower_account
        new_order.orderRef = f"{self.config.copier_tag}:{mapping.primary_order_id}"

        if self.config.dry_run:
            self.logger.info(
                "[DRY RUN] Would modify follower order",
                extra={
                    "follower_account": mapping.follower_account,
                    "old_order_id": mapping.follower_order_id,
                    "symbol": contract.symbol
                }
            )
            return

        # Rate limiting
        await self.rate_limiter.acquire()

        # Cancel old order
        try:
            # Find the old order
            trades = self.ib.trades()
            old_trade = next((t for t in trades if t.order.orderId == mapping.follower_order_id), None)

            if old_trade:
                self.ib.cancelOrder(old_trade.order)
                await asyncio.sleep(0.5)

        except Exception as e:
            self.logger.warning(f"Failed to cancel old order {mapping.follower_order_id}: {e}")

        # Place new order
        await self.rate_limiter.acquire()
        new_trade = self.ib.placeOrder(contract, new_order)
        await asyncio.sleep(0.5)

        # Update mapping
        mapping.follower_order_id = new_order.orderId
        mapping.quantity = new_quantity
        mapping.order_type = new_order.orderType
        mapping.updated_at = datetime.utcnow().isoformat()
        self.state_store.save_mapping(mapping)

        self.logger.info(
            f"Modified follower order {mapping.follower_order_id}",
            extra={
                "follower_account": mapping.follower_account,
                "symbol": contract.symbol
            }
        )

    async def handle_order_cancelled(self, trade: Trade):
        """Handle cancellation of a primary order."""
        try:
            primary_order_id = trade.order.orderId
            contract = trade.contract

            self.logger.info(
                f"Handling order cancellation {primary_order_id}",
                extra={"symbol": contract.symbol}
            )

            # Get follower orders
            follower_mappings = self.state_store.get_follower_orders(primary_order_id)

            if not follower_mappings:
                self.logger.warning(f"No follower orders found for {primary_order_id}")
                return

            # Cancel all follower orders
            for mapping in follower_mappings:
                if not self.config.is_follower_enabled(mapping.follower_account):
                    continue

                try:
                    await self._cancel_follower_order(mapping)
                except Exception as e:
                    self.logger.error(
                        f"Failed to cancel follower order for {mapping.follower_account}: {e}",
                        exc_info=True
                    )

        except Exception as e:
            self.logger.error(f"Error handling order cancellation: {e}", exc_info=True)

    async def _cancel_follower_order(self, mapping: OrderMapping):
        """Cancel a follower order."""
        if self.config.dry_run:
            self.logger.info(
                "[DRY RUN] Would cancel follower order",
                extra={
                    "follower_account": mapping.follower_account,
                    "order_id": mapping.follower_order_id,
                    "symbol": mapping.symbol
                }
            )
            return

        # Rate limiting
        await self.rate_limiter.acquire()

        # Find and cancel the order
        trades = self.ib.trades()
        follower_trade = next((t for t in trades if t.order.orderId == mapping.follower_order_id), None)

        if follower_trade:
            self.ib.cancelOrder(follower_trade.order)
            await asyncio.sleep(0.5)

            self.logger.info(
                f"Cancelled follower order {mapping.follower_order_id}",
                extra={
                    "follower_account": mapping.follower_account,
                    "symbol": mapping.symbol
                }
            )

            # Update status
            self.state_store.update_status(
                mapping.primary_order_id,
                mapping.follower_account,
                "CANCELLED"
            )
        else:
            self.logger.warning(f"Could not find follower order {mapping.follower_order_id}")

    async def handle_order_filled(self, trade: Trade):
        """Handle fill of a primary order (logging only)."""
        try:
            primary_order_id = trade.order.orderId
            contract = trade.contract
            order_status = trade.orderStatus

            self.logger.info(
                f"Order filled {primary_order_id}",
                extra={
                    "symbol": contract.symbol,
                    "filled_quantity": order_status.filled,
                    "avg_fill_price": order_status.avgFillPrice
                }
            )

            # Update follower order statuses
            follower_mappings = self.state_store.get_follower_orders(primary_order_id)
            for mapping in follower_mappings:
                self.state_store.update_status(
                    mapping.primary_order_id,
                    mapping.follower_account,
                    "FILLED"
                )

        except Exception as e:
            self.logger.error(f"Error handling order fill: {e}", exc_info=True)
