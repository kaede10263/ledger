import yfinance as yf
from typing import Dict, Optional

from models.asset import AssetType
from .base_adapter import BasePriceAdapter


class StockPriceAdapter(BasePriceAdapter):
    """股票價格適配器（支援台股、美股、港股、基金）"""
    
    def __init__(self):
        self._cache: Dict[str, float] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_duration = 30  # 快取30秒（確保使用較新的價格數據）
    
    def _get_yahoo_symbol(self, symbol: str, asset_type: AssetType) -> str:
        """轉換為 Yahoo Finance 代號格式"""
        if asset_type == AssetType.TAIWAN_STOCK:
            # 台股（上市）格式: 2330.TW
            # 上櫃常見為 2330.TWO（會在 get_price / get_stock_name 內自動嘗試）
            return f"{symbol}.TW"
        elif asset_type == AssetType.US_STOCK:
            # 美股直接使用
            return symbol
        elif asset_type == AssetType.HK_STOCK:
            # 港股（Yahoo 常用 0700.HK）
            if "." not in symbol:
                return f"{symbol}.HK"
            return symbol
        elif asset_type == AssetType.FUND:
            # 基金處理
            # 如果是台灣基金 ISIN 格式 (TW開頭)，嘗試轉換
            if symbol.startswith('TW') and len(symbol) == 12:
                # ISIN 格式: TW000T3201Y8 -> 可能需要轉換為基金代號
                # 嘗試多種格式
                # 1. 直接使用 ISIN
                # 2. 嘗試 .TW 後綴
                # 3. 嘗試提取數字部分
                return f"{symbol}.TW"
            # 其他基金直接使用或嘗試 .TW
            if not symbol.endswith('.TW') and not '.' in symbol:
                # 可能是台灣基金，嘗試添加 .TW
                return f"{symbol}.TW"
            return symbol
        return symbol
    
    def get_stock_name(self, symbol: str, asset_type: Optional[AssetType] = None) -> Optional[str]:
        """獲取股票名稱"""
        if asset_type is None:
            asset_type = AssetType.US_STOCK
        yahoo_symbol = self._get_yahoo_symbol(symbol, asset_type)

        symbols_to_try = [yahoo_symbol]
        if asset_type == AssetType.TAIWAN_STOCK and "." not in symbol:
            # Yahoo Finance: 上市多為 .TW，上櫃多為 .TWO
            symbols_to_try = [f"{symbol}.TW", f"{symbol}.TWO"]
        
        for try_symbol in symbols_to_try:
            try:
                ticker = yf.Ticker(try_symbol)
                info = ticker.info
                # 嘗試獲取多種可能的名稱欄位
                name = info.get("longName") or info.get("shortName") or info.get("name")
                if name:
                    return name
            except Exception:
                continue

        return None
    
    def get_price(self, symbol: str, asset_type: Optional[AssetType] = None) -> Optional[float]:
        """獲取單一股票價格（獲取最新數據）"""
        if asset_type is None:
            asset_type = AssetType.US_STOCK
        yahoo_symbol = self._get_yahoo_symbol(symbol, asset_type)
        
        # 檢查快取（但優先獲取最新數據）
        cache_key = f"{yahoo_symbol}_{asset_type.value}"
        import time
        if cache_key in self._cache and cache_key in self._cache_time:
            elapsed = time.time() - self._cache_time[cache_key]
            if elapsed < self._cache_duration:
                return self._cache[cache_key]
        
        # 嘗試多種格式（特別是台灣基金 / 台股上市上櫃）
        symbols_to_try = [yahoo_symbol]
        if asset_type == AssetType.TAIWAN_STOCK and "." not in symbol:
            # Yahoo Finance: 上市多為 .TW，上櫃多為 .TWO
            symbols_to_try = [f"{symbol}.TW", f"{symbol}.TWO"]
        if asset_type == AssetType.FUND:
            # 如果是基金，嘗試多種格式
            if symbol.startswith('TW') and len(symbol) >= 10:
                # 台灣基金 ISIN 格式 (TW000T3201Y8)
                # 嘗試多種可能的格式
                symbols_to_try = [
                    f"{symbol}.TW",  # TW000T3201Y8.TW
                    symbol,  # TW000T3201Y8 (直接使用)
                    yahoo_symbol,
                ]
                # 嘗試從 ISIN 提取可能的基金代號
                if len(symbol) == 12:
                    # ISIN: TW000T3201Y8
                    # 嘗試提取數字部分作為基金代號
                    try:
                        # 提取中間的數字部分 (000T3201 -> 3201)
                        numeric_chars = ''.join(c for c in symbol[4:10] if c.isdigit())
                        if numeric_chars:
                            symbols_to_try.append(f"{numeric_chars}.TW")
                            # 也嘗試完整數字部分
                            full_numeric = ''.join(c for c in symbol[2:10] if c.isdigit())
                            if full_numeric and full_numeric != numeric_chars:
                                symbols_to_try.append(f"{full_numeric}.TW")
                    except:
                        pass
            elif not symbol.endswith('.TW') and not '.' in symbol:
                # 其他可能的台灣基金代號，嘗試添加 .TW
                symbols_to_try.append(f"{symbol}.TW")
        
        for try_symbol in symbols_to_try:
            try:
                ticker = yf.Ticker(try_symbol)
                
                # 優先獲取最新數據（使用 1m 間隔）
                data = ticker.history(period="1d", interval="1m")
                
                if not data.empty:
                    # 使用最新價格
                    current_price = float(data['Close'].iloc[-1])
                    # 更新快取
                    self._cache[cache_key] = current_price
                    self._cache_time[cache_key] = time.time()
                    return current_price
                
                # 如果 1m 數據為空，嘗試 5m 數據
                data = ticker.history(period="1d", interval="5m")
                if not data.empty:
                    current_price = float(data['Close'].iloc[-1])
                    self._cache[cache_key] = current_price
                    self._cache_time[cache_key] = time.time()
                    return current_price
                
                # 如果還是空，嘗試 1d 數據
                data = ticker.history(period="5d", interval="1d")
                if not data.empty:
                    current_price = float(data['Close'].iloc[-1])
                    self._cache[cache_key] = current_price
                    self._cache_time[cache_key] = time.time()
                    return current_price
            except Exception as e:
                continue  # 嘗試下一個格式
        
        # 所有格式都失敗
        if asset_type == AssetType.FUND:
            print(f"Warning: Unable to fetch price for fund {symbol}. Tried formats: {symbols_to_try}")
            print("Note: Taiwan funds with ISIN format may not be supported by Yahoo Finance.")
            print("Please try using the fund's trading symbol instead of ISIN if available.")
        elif asset_type == AssetType.TAIWAN_STOCK:
            print(f"Warning: Unable to fetch price for TW stock {symbol}. Tried formats: {symbols_to_try}")
        else:
            print(f"Warning: Unable to fetch price for {symbol}. Tried formats: {symbols_to_try}")
        return None
    
    def get_prices(self, symbols: Dict[str, AssetType]) -> Dict[str, Optional[float]]:
        """批量獲取股票價格"""
        results = {}
        for symbol, asset_type in symbols.items():
            results[symbol] = self.get_price(symbol, asset_type)
        return results
    
    def supports(self, asset_type: AssetType) -> bool:
        """支援台股、美股、基金"""
        return asset_type in [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND]
