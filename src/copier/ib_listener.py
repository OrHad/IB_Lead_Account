"""Order listener for the primary account."""
import logging
from typing import Callable, Optional, Set
from ib_insync import IB, Order, Trade, OrderStatus

from .config import Config


class OrderListener:
    """Listens to order events from the primary account."""

    def __init__(
        self,
        ib: IB,
        config: Config,
        on_new_order: Callable,
        on_order_modified: Callable,
        on_order_cancelled: Callable,
        on_order_filled: Callable
    ):
        """Initialize the order listener."""
        self.ib = ib
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Callbacks
        self._on_new_order = on_new_order
        self._on_order_modified = on_order_modified
        self._on_order_cancelled = on_order_cancelled
        self._on_order_filled = on_order_filled

        # Track seen orders to detect new vs. modified
        self._seen_orders: Set[int] = set()

        # Track order status to detect changes
        self._order_status: dict[int, str] = {}

    def start(self):
        """Start listening to order events."""
        self.logger.info("Starting order listener")

        # Subscribe to order status events
        self.ib.orderStatusEvent += self._on_order_status
        self.ib.openOrderEvent += self._on_open_order
        self.ib.execDetailsEvent += self._on_execution

        # Request existing open orders to build initial state
        self._load_existing_orders()

    def stop(self):
        """Stop listening to order events."""
        self.logger.info("Stopping order listener")

        # Unsubscribe from events
        self.ib.orderStatusEvent -= self._on_order_status
        self.ib.openOrderEvent -= self._on_open_order
        self.ib.execDetailsEvent -= self._on_execution

    def _load_existing_orders(self):
        """Load existing open orders to build initial state."""
        try:
            trades = self.ib.openTrades()
            self.logger.info(f"Loading {len(trades)} existing open orders")

            for trade in trades:
                order_id = trade.order.orderId

                # Skip if this is a copier-generated order
                if self._is_copier_order(trade.order):
                    self.logger.debug(f"Skipping copier order: {order_id}")
                    continue

                # Only track orders from primary account
                if trade.order.account != self.config.primary_account:
                    continue

                self._seen_orders.add(order_id)
                self._order_status[order_id] = trade.orderStatus.status

                self.logger.debug(
                    f"Loaded existing order: {order_id}",
                    extra={
                        "symbol": trade.contract.symbol,
                        "action": trade.order.action,
                        "status": trade.orderStatus.status
                    }
                )

        except Exception as e:
            self.logger.error(f"Error loading existing orders: {e}")

    def _on_open_order(self, trade: Trade):
        """Handle open order event."""
        try:
            order = trade.order
            order_id = order.orderId
            contract = trade.contract
            order_status = trade.orderStatus

            # Skip if not from primary account
            if order.account != self.config.primary_account:
                return

            # Skip copier-generated orders
            if self._is_copier_order(order):
                self.logger.debug(f"Ignoring copier order: {order_id}")
                return

            # Skip if symbol is not in copy list
            if not self.config.should_copy_symbol(contract.symbol):
                self.logger.debug(f"Symbol {contract.symbol} not in copy list, skipping")
                return

            # Determine if this is a new order or modification
            is_new = order_id not in self._seen_orders

            if is_new:
                self._seen_orders.add(order_id)
                self._order_status[order_id] = order_status.status

                self.logger.info(
                    f"New order detected: {order_id}",
                    extra={
                        "symbol": contract.symbol,
                        "action": order.action,
                        "quantity": order.totalQuantity,
                        "order_type": order.orderType,
                        "status": order_status.status
                    }
                )

                # Trigger new order callback
                self._on_new_order(trade)

            else:
                # Check if order was modified
                old_status = self._order_status.get(order_id)
                if old_status != order_status.status or self._order_changed(trade):
                    self._order_status[order_id] = order_status.status

                    self.logger.info(
                        f"Order modified: {order_id}",
                        extra={
                            "symbol": contract.symbol,
                            "old_status": old_status,
                            "new_status": order_status.status
                        }
                    )

                    # Trigger modification callback
                    self._on_order_modified(trade)

        except Exception as e:
            self.logger.error(f"Error handling open order: {e}", exc_info=True)

    def _on_order_status(self, trade: Trade):
        """Handle order status event."""
        try:
            order = trade.order
            order_id = order.orderId
            order_status = trade.orderStatus

            # Skip if not from primary account
            if order.account != self.config.primary_account:
                return

            # Skip copier-generated orders
            if self._is_copier_order(order):
                return

            # Skip if symbol is not in copy list
            if not self.config.should_copy_symbol(trade.contract.symbol):
                return

            old_status = self._order_status.get(order_id)
            new_status = order_status.status

            # Update status
            self._order_status[order_id] = new_status

            # Handle cancellation
            if new_status in ("Cancelled", "ApiCancelled"):
                self.logger.info(
                    f"Order cancelled: {order_id}",
                    extra={
                        "symbol": trade.contract.symbol,
                        "old_status": old_status
                    }
                )
                self._on_order_cancelled(trade)

            # Handle fill
            elif new_status == "Filled":
                self.logger.info(
                    f"Order filled: {order_id}",
                    extra={
                        "symbol": trade.contract.symbol,
                        "filled_quantity": order_status.filled
                    }
                )
                self._on_order_filled(trade)

        except Exception as e:
            self.logger.error(f"Error handling order status: {e}", exc_info=True)

    def _on_execution(self, trade: Trade, fill):
        """Handle execution event."""
        try:
            order = trade.order
            order_id = order.orderId

            # Skip if not from primary account
            if order.account != self.config.primary_account:
                return

            # Skip copier-generated orders
            if self._is_copier_order(order):
                return

            self.logger.info(
                f"Execution detected: {order_id}",
                extra={
                    "symbol": trade.contract.symbol,
                    "shares": fill.shares,
                    "price": fill.avgPrice,
                    "side": fill.side
                }
            )

        except Exception as e:
            self.logger.error(f"Error handling execution: {e}", exc_info=True)

    def _is_copier_order(self, order: Order) -> bool:
        """Check if an order was placed by the copier (to prevent loops)."""
        # Check orderRef field
        if order.orderRef and self.config.copier_tag in order.orderRef:
            return True

        # Could also check other fields like algoStrategy if needed
        return False

    def _order_changed(self, trade: Trade) -> bool:
        """Check if order parameters changed (price, quantity, etc.)."""
        # This is a simplified check - in production you might want to track
        # previous order parameters and compare them
        # For now, we rely on status changes
        return False

    def rebuild_state_on_reconnect(self):
        """Rebuild listener state after reconnection."""
        self.logger.info("Rebuilding order listener state after reconnect")

        # Clear state
        self._seen_orders.clear()
        self._order_status.clear()

        # Reload existing orders
        self._load_existing_orders()
