from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from .asset import AssetType


class TransactionType(Enum):
    """交易類型"""
    BUY = "買入"
    SELL = "賣出"


@dataclass
class Transaction:
    """交易記錄模型"""
    id: str  # 交易ID
    symbol: str  # 代號
    name: str  # 名稱
    asset_type: AssetType  # 資產類型
    transaction_type: TransactionType  # 交易類型
    quantity: float  # 數量
    price: float  # 價格
    date: datetime  # 交易日期
    fee: float = 0.0  # 手續費
    unit: Optional[str] = None  # 單位（用於黃金：盎司、g、錢、兩）
    currency: str = "TWD"  # 貨幣（TWD 或 USD）
    notes: Optional[str] = None  # 備註
