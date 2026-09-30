"""持倉記錄模型"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    """單筆持倉記錄（同一資產的不同買入時間點）"""
    transaction_id: str  # 對應的交易ID
    quantity: float  # 數量
    cost_price: float  # 成本價（含手續費）
    buy_date: datetime  # 買入日期
    current_price: float = 0.0  # 當前價格
    last_updated: Optional[datetime] = None  # 最後更新時間
    
    @property
    def total_cost(self) -> float:
        """總成本"""
        return self.quantity * self.cost_price
    
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
