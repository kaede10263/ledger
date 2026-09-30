from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List

from .position import Position


class AssetType(Enum):
    """資產類型"""
    TAIWAN_STOCK = "台股"
    US_STOCK = "美股"
    HK_STOCK = "港股"
    FUND = "基金"
    CRYPTO = "Crypto"
    METAL = "貴金屬"


@dataclass
class Asset:
    """資產資料模型"""
    symbol: str  # 代號
    name: str  # 名稱
    asset_type: AssetType  # 資產類型
    unit: str = "股"  # 單位（股、盎司、g、錢、兩等）
    quantity: float = 0.0  # 持有數量
    avg_cost: float = 0.0  # 平均成本
    current_price: float = 0.0  # 當前價格
    last_updated: Optional[datetime] = None  # 最後更新時間
    positions: List[Position] = field(default_factory=list)  # 多筆持倉記錄
    # 由 PortfolioManager 依交易 FIFO 計算：賣出已實現損益、累計買入付出金額（含手續費）
    realized_pnl: float = 0.0
    total_buy_cash: float = 0.0

    @property
    def total_cost(self) -> float:
        """總成本"""
        return self.quantity * self.avg_cost
    
    @property
    def current_value(self) -> float:
        """當前市值"""
        return self.quantity * self.current_price
    
    @property
    def unrealized_pnl(self) -> float:
        """未實現損益"""
        return self.current_value - self.total_cost
    
    @property
    def unrealized_pnl_percent(self) -> float:
        """未實現損益百分比"""
        if self.total_cost == 0:
            return 0.0
        return (self.unrealized_pnl / self.total_cost) * 100

    @property
    def total_pnl(self) -> float:
        """已實現 + 未實現損益（同幣別）"""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def total_pnl_percent(self) -> float:
        """相對累計買入金額的總報酬率（含已賣出部位）"""
        if self.total_buy_cash <= 0:
            return 0.0
        return (self.total_pnl / self.total_buy_cash) * 100

    def get_unit_display(self) -> str:
        """獲取單位顯示文字"""
        if self.asset_type in [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND]:
            return "股"
        elif self.asset_type == AssetType.METAL:
            return self.unit
        elif self.asset_type == AssetType.CRYPTO:
            return self.symbol.split('/')[0] if '/' in self.symbol else self.symbol
        return self.unit
