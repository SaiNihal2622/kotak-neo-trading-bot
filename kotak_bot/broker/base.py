"""Abstract broker interface. Both NeoClient and PaperClient implement this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ProductType(str, Enum):
    MIS = "MIS"  # intraday
    NRML = "NRML"  # normal (carry forward)
    CNC = "CNC"  # delivery


@dataclass
class Order:
    symbol: str
    side: OrderSide
    qty: int
    order_type: OrderType
    product: ProductType
    price: float = 0.0
    trigger_price: float = 0.0
    tag: str = ""
    exchange: str = "NFO"
    strike: float = 0.0
    option_type: Optional[str] = None  # "CE" or "PE" for options
    expiry: Optional[str] = None  # YYYY-MM-DD
    underlying: Optional[str] = None  # "NIFTY" / "BANKNIFTY"

    # filled by broker
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    placed_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    rejection_reason: str = ""

    # for paper trading
    expected_fill_price: float = 0.0


@dataclass
class Position:
    symbol: str
    exchange: str
    qty: int  # +ve long, -ve short
    avg_price: float
    ltp: float
    pnl: float = 0.0
    product: ProductType = ProductType.MIS
    strike: float = 0.0
    option_type: Optional[str] = None
    expiry: Optional[str] = None
    underlying: Optional[str] = None
    entry_time: Optional[datetime] = None

    @property
    def is_option(self) -> bool:
        return self.option_type in ("CE", "PE")

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.avg_price


@dataclass
class Tick:
    symbol: str
    ltp: float
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0
    oi: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    exchange: str = "NFO"
    strike: float = 0.0
    option_type: Optional[str] = None
    expiry: Optional[str] = None
    underlying: Optional[str] = None


class BrokerClient(ABC):
    """Abstract broker — same API for paper and live."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    def modify_order(self, order_id: str, **kwargs) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> Order: ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_holdings(self) -> list[Position]: ...

    @abstractmethod
    def get_margins(self) -> dict: ...

    @abstractmethod
    def get_ltp(self, symbol: str, exchange: str = "NFO") -> float: ...

    @abstractmethod
    def subscribe(self, symbols: list[str], exchange: str = "NFO") -> None: ...

    @abstractmethod
    def on_tick(self, callback) -> None: ...
