import yfinance as yf
from typing import Dict, Optional

from models.asset import AssetType
from .base_adapter import BasePriceAdapter


class GoldPriceAdapter(BasePriceAdapter):
    """黃金價格適配器"""
    
    def __init__(self):
        # 金屬類型對應的 Yahoo Finance 代號
        self.metal_symbols = {
            '黃金': 'GC=F',      # COMEX 黃金期貨
            '白銀': 'SI=F',      # COMEX 白銀期貨
            '白金': 'PL=F',      # NYMEX 白金期貨
            '鈀金': 'PA=F',      # NYMEX 鈀金期貨
            'GC=F': 'GC=F',      # 直接使用代號
            'SI=F': 'SI=F',
            'PL=F': 'PL=F',
            'PA=F': 'PA=F'
        }
    
    def _get_yahoo_symbol(self, symbol: str) -> str:
        """將金屬名稱轉換為 Yahoo Finance 代號"""
        return self.metal_symbols.get(symbol, 'GC=F')  # 預設為黃金
    
    def get_price(self, symbol: str = 'GC=F', asset_type: Optional[AssetType] = None) -> Optional[float]:
        """
        獲取金屬價格（單位：美元/盎司，獲取最新數據）
        
        注意：Yahoo Finance 的金屬期貨價格單位是美元/盎司
        例如：GC=F (黃金期貨) 的價格是每盎司的美元價格
        """
        try:
            # 將中文名稱或代號轉換為 Yahoo Finance 代號
            ticker_symbol = self._get_yahoo_symbol(symbol)
            ticker = yf.Ticker(ticker_symbol)
            
            # 優先獲取最新數據（使用 1m 間隔）
            data = ticker.history(period="1d", interval="1m")
            
            if data.empty:
                # 如果 1m 數據為空，嘗試 5m 數據
                data = ticker.history(period="1d", interval="5m")
                if data.empty:
                    # 如果還是空，嘗試 1d 數據
                    data = ticker.history(period="5d", interval="1d")
                    if data.empty:
                        return None
            
            # 返回最新價格（單位：美元/盎司）
            current_price = float(data['Close'].iloc[-1])
            return current_price
        except Exception as e:
            print(f"Error fetching metal price for {symbol}: {e}")
            return None
    
    def get_prices(self, symbols: Dict[str, AssetType]) -> Dict[str, Optional[float]]:
        """批量獲取黃金價格"""
        results = {}
        for symbol, asset_type in symbols.items():
            results[symbol] = self.get_price(symbol)
        return results
    
    def supports(self, asset_type: AssetType) -> bool:
        """支援金屬（黃金、白銀等）"""
        return asset_type == AssetType.METAL
