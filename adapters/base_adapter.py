from abc import ABC, abstractmethod
from typing import Dict, Optional

from models.asset import AssetType


class BasePriceAdapter(ABC):
    """價格資料來源適配器基類"""
    
    @abstractmethod
    def get_price(self, symbol: str, asset_type: Optional[AssetType] = None) -> Optional[float]:
        """獲取資產當前價格"""
        pass
    
    @abstractmethod
    def get_prices(self, symbols: Dict[str, AssetType]) -> Dict[str, Optional[float]]:
        """批量獲取資產價格"""
        pass
    
    @abstractmethod
    def supports(self, asset_type: AssetType) -> bool:
        """檢查是否支援該資產類型"""
        pass
