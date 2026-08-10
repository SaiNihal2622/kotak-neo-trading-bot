"""Broker abstraction layer.

- neo_client.py: real Kotak Neo API wrapper (neo_api_client v2)
- paper_client.py: paper-trading client that synthesizes fills from live WS LTP
- base.py: abstract BrokerClient interface
"""
from .base import (
    BrokerClient,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    ProductType,
    Tick,
)
from .paper_client import PaperClient
from .neo_client import NeoClient

__all__ = [
    "BrokerClient",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Position",
    "ProductType",
    "Tick",
    "PaperClient",
    "NeoClient",
]
