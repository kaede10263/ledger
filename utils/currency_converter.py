"""貨幣轉換工具"""
import yfinance as yf
from typing import Optional
from datetime import datetime


class CurrencyConverter:
    """貨幣轉換器"""
    
    def __init__(self):
        self._usd_twd_rate: Optional[float] = None
        self._hkd_twd_rate: Optional[float] = None
        self._last_update: Optional[datetime] = None
        self._cache_duration = 60  # 快取60秒（確保使用最新的匯率數據）
    
    def get_usd_to_twd_rate(self, force_update: bool = False) -> Optional[float]:
        """
        獲取 USD 到 TWD 的匯率
        
        Args:
            force_update: 是否強制更新（忽略快取）
        """
        # 檢查快取（除非強制更新）
        if not force_update and self._usd_twd_rate and self._last_update:
            elapsed = (datetime.now() - self._last_update).total_seconds()
            if elapsed < self._cache_duration:
                return self._usd_twd_rate
        
        try:
            # 使用 USD/TWD 匯率，獲取最新數據
            ticker = yf.Ticker("USDTWD=X")
            # 嘗試獲取最新數據（使用更短的時間間隔）
            data = ticker.history(period="1d", interval="1m")
            
            if data.empty:
                # 如果 1m 數據為空，嘗試 5m 數據
                data = ticker.history(period="1d", interval="5m")
                if data.empty:
                    # 如果還是空，使用預設匯率
                    if not self._usd_twd_rate:
                        return 32.0
                    return self._usd_twd_rate
            
            current_rate = float(data['Close'].iloc[-1])
            self._usd_twd_rate = current_rate
            self._last_update = datetime.now()
            return current_rate
        except Exception as e:
            print(f"Error fetching exchange rate: {e}")
            # 如果之前有快取的匯率，使用它；否則使用預設匯率
            if self._usd_twd_rate:
                return self._usd_twd_rate
            return 32.0

    def get_hkd_to_twd_rate(self, force_update: bool = False) -> Optional[float]:
        """
        獲取 HKD 到 TWD 的匯率。
        """
        if not force_update and self._hkd_twd_rate and self._last_update:
            elapsed = (datetime.now() - self._last_update).total_seconds()
            if elapsed < self._cache_duration:
                return self._hkd_twd_rate

        try:
            ticker = yf.Ticker("HKDTWD=X")
            data = ticker.history(period="1d", interval="1m")
            if data.empty:
                data = ticker.history(period="1d", interval="5m")
                if data.empty:
                    if not self._hkd_twd_rate:
                        return 4.1
                    return self._hkd_twd_rate
            current_rate = float(data["Close"].iloc[-1])
            self._hkd_twd_rate = current_rate
            self._last_update = datetime.now()
            return current_rate
        except Exception as e:
            print(f"Error fetching HKD/TWD exchange rate: {e}")
            if self._hkd_twd_rate:
                return self._hkd_twd_rate
            return 4.1
    
    def convert_to_twd(self, amount: float, currency: str) -> float:
        """將金額轉換為台幣"""
        if currency == "TWD":
            return amount
        elif currency == "USD":
            rate = self.get_usd_to_twd_rate()
            return amount * rate
        elif currency == "HKD":
            rate = self.get_hkd_to_twd_rate()
            return amount * rate
        return amount
    
    def convert_from_twd(self, amount_twd: float, target_currency: str) -> float:
        """從台幣轉換為目標貨幣"""
        if target_currency == "TWD":
            return amount_twd
        elif target_currency == "USD":
            rate = self.get_usd_to_twd_rate()
            return amount_twd / rate if rate > 0 else amount_twd
        elif target_currency == "HKD":
            rate = self.get_hkd_to_twd_rate()
            return amount_twd / rate if rate > 0 else amount_twd
        return amount_twd
