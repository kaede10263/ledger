"""投資組合管理器"""
from collections import defaultdict
from datetime import datetime, date as date_type, time as time_type, timedelta
from typing import Dict, List, Optional
import uuid

from models.asset import Asset, AssetType
from models.transaction import Transaction, TransactionType
from models.position import Position
from adapters import StockPriceAdapter, CryptoPriceAdapter, GoldPriceAdapter
from utils.gold_converter import convert_to_grams, convert_from_grams, GOLD_UNIT_CONVERSIONS
from utils.currency_converter import CurrencyConverter
from database.db_manager import DatabaseManager


class PortfolioManager:
    """管理投資組合的核心類別"""
    
    def __init__(self, db_path: str = "portfolio.db"):
        self.db_manager = DatabaseManager(db_path)
        self.transactions: List[Transaction] = []
        self.assets: Dict[str, Asset] = {}
        # FIFO 計算用：每筆 SELL 的已實現損益與分母（賣出成本）
        # key: transaction.id
        self.realized_pnl_by_transaction_id: Dict[str, float] = {}
        self.realized_cost_basis_by_transaction_id: Dict[str, float] = {}
        # FIFO 計算用：每筆 BUY 最終仍剩下的持有量/成本基礎（用來算未實現的市值損益）
        # key: transaction.id
        self.buy_remaining_qty_by_transaction_id: Dict[str, float] = {}
        self.buy_remaining_cost_basis_by_transaction_id: Dict[str, float] = {}
        self.adapters = {
            StockPriceAdapter(),
            CryptoPriceAdapter(),
            GoldPriceAdapter()
        }
        self.currency_converter = CurrencyConverter()
        # 載入已儲存的交易記錄
        self.load_from_database()
    
    def add_transaction(self, transaction: Transaction):
        """新增交易記錄"""
        self.transactions.append(transaction)
        self.db_manager.save_transaction(transaction)
        # 依日期重算持倉與已實現損益（與 FIFO 一致）
        self._recalculate_assets()

    def update_transaction(self, updated: Transaction):
        """更新既有交易記錄（用 id 覆蓋），並重新計算資產。"""
        found = False
        for i, t in enumerate(self.transactions):
            if t.id == updated.id:
                self.transactions[i] = updated
                found = True
                break
        if not found:
            # 若資料不一致，視同新增（仍可避免 UI 卡死）
            self.transactions.append(updated)
        self.db_manager.save_transaction(updated)
        self._recalculate_assets()
    
    def _update_asset_from_transaction(self, transaction: Transaction):
        """根據交易更新資產"""
        key = f"{transaction.symbol}_{transaction.asset_type.value}"
        
        if key not in self.assets:
            # 設定單位
            unit = "股"
            if transaction.asset_type == AssetType.METAL:
                # 金屬：使用第一筆交易的單位，如果沒有則預設為「錢」
                unit = transaction.unit or "錢"
            elif transaction.asset_type in [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND]:
                unit = "股"
            
            self.assets[key] = Asset(
                symbol=transaction.symbol,
                name=transaction.name,
                asset_type=transaction.asset_type,
                unit=unit,
                quantity=0.0,
                avg_cost=0.0
            )
        
        asset = self.assets[key]
        
        # 如果金屬資產已經存在但單位不同，統一使用第一筆交易的單位
        if transaction.asset_type == AssetType.METAL and transaction.unit and transaction.unit != asset.unit:
            # 保持使用 asset.unit（第一筆交易的單位），後續交易會轉換
            pass
        
        if transaction.transaction_type == TransactionType.BUY:
            # 處理金屬單位轉換（統一轉換為盎司，因為價格是盎司價格）
            quantity = transaction.quantity
            price = transaction.price
            
            if transaction.asset_type == AssetType.METAL and transaction.unit:
                # 如果用戶使用的單位不是盎司，需要轉換
                if transaction.unit != "盎司":
                    # 將數量轉換為盎司
                    grams = convert_to_grams(quantity, transaction.unit)
                    quantity = convert_from_grams(grams, "盎司")
                    # 價格也需要轉換（如果用戶輸入的是每單位價格）
                    # 假設用戶輸入的價格是每單位（g/錢/兩）的價格，需要轉換為每盎司價格
                    price_per_unit = transaction.price
                    grams_per_unit = GOLD_UNIT_CONVERSIONS.get(transaction.unit, 1.0)
                    price = price_per_unit * (31.1035 / grams_per_unit)  # 轉換為每盎司價格
            
            # 買入：新增一筆持倉記錄
            cost_price = price + (transaction.fee / quantity) if quantity > 0 else price
            position = Position(
                transaction_id=transaction.id,
                quantity=quantity,
                cost_price=cost_price,
                buy_date=transaction.date
            )
            asset.positions.append(position)
            
            # 更新總數量和平均成本（使用轉換後的數量）
            total_cost = asset.total_cost + (quantity * price) + transaction.fee
            total_quantity = asset.quantity + quantity
            asset.avg_cost = total_cost / total_quantity if total_quantity > 0 else 0.0
            asset.quantity = total_quantity
        elif transaction.transaction_type == TransactionType.SELL:
            # 賣出：使用 FIFO 方法減少持倉（數量單位與買入一致：金屬為盎司）
            remaining_sell = transaction.quantity
            price = transaction.price
            if transaction.asset_type == AssetType.METAL and transaction.unit and transaction.unit != "盎司":
                grams = convert_to_grams(transaction.quantity, transaction.unit)
                remaining_sell = convert_from_grams(grams, "盎司")
                grams_per_unit = GOLD_UNIT_CONVERSIONS.get(transaction.unit, 1.0)
                price = transaction.price * (31.1035 / grams_per_unit)
            
            for position in asset.positions:
                if remaining_sell <= 0:
                    break
                
                if position.quantity <= remaining_sell:
                    remaining_sell -= position.quantity
                    # 保留已了結的買入 lot（quantity 設為 0），讓 UI 可展開查看清單
                    position.quantity = 0.0
                else:
                    position.quantity -= remaining_sell
                    remaining_sell = 0
            
            # 更新總數量
            asset.quantity = sum(pos.quantity for pos in asset.positions)
            
            # 重新計算平均成本
            if asset.quantity > 0:
                total_cost = sum(pos.total_cost for pos in asset.positions)
                asset.avg_cost = total_cost / asset.quantity
            else:
                asset.avg_cost = 0.0

    @staticmethod
    def _tx_qty_price_oz_or_shares(transaction: Transaction) -> tuple[float, float]:
        """買賣共用的數量/單價（金屬統一為盎司與每盎司價）。"""
        quantity = transaction.quantity
        price = transaction.price
        if transaction.asset_type == AssetType.METAL and transaction.unit and transaction.unit != "盎司":
            grams = convert_to_grams(quantity, transaction.unit)
            quantity = convert_from_grams(grams, "盎司")
            grams_per_unit = GOLD_UNIT_CONVERSIONS.get(transaction.unit, 1.0)
            price = transaction.price * (31.1035 / grams_per_unit)
        return quantity, price

    def _compute_fifo_realized_by_asset(self, ordered: List[Transaction]) -> Dict[str, Dict[str, float]]:
        """依日期順序對每檔資產做 FIFO，累計已實現損益與買入總支出。

        同時回傳每筆 SELL 的已實現損益與分母（用於 UI 顯示百分比）。
        """
        from collections import defaultdict

        by_key: Dict[str, List[Transaction]] = defaultdict(list)
        for t in ordered:
            k = f"{t.symbol}_{t.asset_type.value}"
            by_key[k].append(t)

        result: Dict[str, Dict[str, float]] = {}
        for key, txs in by_key.items():
            txs_sorted = sorted(
                txs,
                key=lambda x: (
                    self._normalize_tx_date(x.date),
                    0 if x.transaction_type == TransactionType.BUY else 1,  # 同天固定先處理買入
                    str(x.id),
                ),
            )
            realized = 0.0
            total_buy_cash = 0.0
            lots: List[List[float]] = []  # [remaining_qty, cost_per_unit 含買入手續費, buy_transaction_id]
            realized_pnl_by_sell_id: Dict[str, float] = {}
            cost_basis_by_sell_id: Dict[str, float] = {}

            for t in txs_sorted:
                if t.transaction_type == TransactionType.BUY:
                    q, p = self._tx_qty_price_oz_or_shares(t)
                    if q <= 0:
                        continue
                    fee = t.fee or 0.0
                    cost_per = p + fee / q
                    lots.append([q, cost_per, t.id])
                    total_buy_cash += q * p + fee
                elif t.transaction_type == TransactionType.SELL:
                    q, p = self._tx_qty_price_oz_or_shares(t)
                    if q <= 0:
                        continue
                    fee = t.fee or 0.0
                    net_proceeds = p * q - fee
                    remaining = q
                    cost_taken = 0.0
                    while remaining > 1e-12 and lots:
                        lot_q, lot_cp, lot_buy_id = lots[0]
                        take = min(lot_q, remaining)
                        cost_taken += take * lot_cp
                        lot_q -= take
                        remaining -= take
                        if lot_q <= 1e-12:
                            lots.pop(0)
                        else:
                            lots[0][0] = lot_q
                    realized_pnl = net_proceeds - cost_taken
                    realized += realized_pnl
                    realized_pnl_by_sell_id[t.id] = realized_pnl
                    cost_basis_by_sell_id[t.id] = cost_taken

            # 收尾：將剩餘每筆 BUY 對應的 qty/cost_basis 收集起來
            buy_remaining_qty_by_buy_id: Dict[str, float] = {}
            buy_remaining_cost_basis_by_buy_id: Dict[str, float] = {}
            for lot_q, lot_cp, lot_buy_id in lots:
                buy_remaining_qty_by_buy_id[lot_buy_id] = buy_remaining_qty_by_buy_id.get(lot_buy_id, 0.0) + float(lot_q)
                buy_remaining_cost_basis_by_buy_id[lot_buy_id] = buy_remaining_cost_basis_by_buy_id.get(lot_buy_id, 0.0) + float(lot_q * lot_cp)

            result[key] = {
                "realized_pnl": realized,
                "total_buy_cash": total_buy_cash,
                "realized_pnl_by_sell_id": realized_pnl_by_sell_id,
                "cost_basis_by_sell_id": cost_basis_by_sell_id,
                "buy_remaining_qty_by_buy_id": buy_remaining_qty_by_buy_id,
                "buy_remaining_cost_basis_by_buy_id": buy_remaining_cost_basis_by_buy_id,
            }
        return result

    def update_prices(self, progress_callback=None):
        """
        更新所有資產的當前價格和匯率。

        Args:
            progress_callback: Optional callable(str) for UI progress/status updates.
        """
        def _progress(msg: str):
            if callable(progress_callback):
                progress_callback(msg)

        _progress("更新匯率...")
        # 先更新匯率（確保使用最新匯率，強制更新）
        self.currency_converter.get_usd_to_twd_rate(force_update=True)
        
        # 按資產類型分組
        assets_by_type: Dict[AssetType, List[Asset]] = defaultdict(list)
        for asset in self.assets.values():
            assets_by_type[asset.asset_type].append(asset)
        
        # 為每種類型找到對應的適配器並更新價格
        for asset_type, assets in assets_by_type.items():
            if asset_type in [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND]:
                _progress(f"更新 {asset_type.value} 股價... ({len(assets)} 檔)")
            elif asset_type == AssetType.CRYPTO:
                _progress(f"更新虛擬貨幣價格... ({len(assets)} 檔)")
            elif asset_type == AssetType.METAL:
                _progress(f"更新貴金屬價格... ({len(assets)} 檔)")
            else:
                _progress(f"更新 {asset_type.value} 價格... ({len(assets)} 檔)")

            adapter = self._get_adapter(asset_type)
            if adapter:
                for asset in assets:
                    # 根據適配器類型傳遞正確的參數
                    if asset_type in [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND]:
                        # 股票適配器需要 symbol 和 asset_type
                        price = adapter.get_price(asset.symbol, asset_type)
                    else:
                        # 加密貨幣和金屬適配器只需要 symbol
                        price = adapter.get_price(asset.symbol)
                    if price is not None:
                        asset.current_price = price
                        asset.last_updated = datetime.now()
                        # 同時更新所有持倉的價格
                        for position in asset.positions:
                            position.current_price = price
                            position.last_updated = datetime.now()

        _progress("價格更新完成")
    
    def _get_adapter(self, asset_type: AssetType):
        """獲取對應資產類型的適配器"""
        for adapter in self.adapters:
            if adapter.supports(asset_type):
                return adapter
        return None
    
    def get_all_assets(self) -> List[Asset]:
        """獲取所有資產列表"""
        return list(self.assets.values())
    
    def get_assets_by_type(self) -> Dict[AssetType, List[Asset]]:
        """按資產類型分組獲取資產"""
        assets_by_type: Dict[AssetType, List[Asset]] = defaultdict(list)
        for asset in self.assets.values():
            assets_by_type[asset.asset_type].append(asset)
        return dict(assets_by_type)
    
    def get_total_value(self, target_currency: str = "TWD", included_types: Optional[List[AssetType]] = None) -> float:
        """
        獲取總市值（轉換為目標貨幣）
        
        Args:
            target_currency: 目標貨幣（預設為 TWD）
            included_types: 要包含的資產類型列表，如果為 None 則包含所有類型
        """
        total = 0.0
        for asset in self.assets.values():
            # 如果指定了包含類型，則過濾
            if included_types is not None and asset.asset_type not in included_types:
                continue
            
            # 獲取該資產當前價格的貨幣
            # 金屬和加密貨幣的當前價格是 USD，其他根據資產類型判斷
            if asset.asset_type == AssetType.METAL or asset.asset_type == AssetType.CRYPTO:
                value_currency = "USD"  # 金屬和加密貨幣的當前價格是美元
            else:
                value_currency = self._get_asset_currency(asset)
            
            value = asset.current_value
            # 轉換為目標貨幣
            if target_currency == "TWD":
                value = self.currency_converter.convert_to_twd(value, value_currency)
            else:
                # 先轉為台幣再轉為目標貨幣
                value_twd = self.currency_converter.convert_to_twd(value, value_currency)
                value = self.currency_converter.convert_from_twd(value_twd, target_currency)
            total += value
        return total
    
    def get_total_cost(self, target_currency: str = "TWD", included_types: Optional[List[AssetType]] = None) -> float:
        """
        獲取總成本（轉換為目標貨幣）
        
        Args:
            target_currency: 目標貨幣（預設為 TWD）
            included_types: 要包含的資產類型列表，如果為 None 則包含所有類型
        """
        total = 0.0
        for asset in self.assets.values():
            # 如果指定了包含類型，則過濾
            if included_types is not None and asset.asset_type not in included_types:
                continue
            
            # 獲取該資產的貨幣
            asset_currency = self._get_asset_currency(asset)
            cost = asset.total_cost
            # 轉換為目標貨幣
            if target_currency == "TWD":
                cost = self.currency_converter.convert_to_twd(cost, asset_currency)
            else:
                cost_twd = self.currency_converter.convert_to_twd(cost, asset_currency)
                cost = self.currency_converter.convert_from_twd(cost_twd, target_currency)
            total += cost
        return total
    
    def get_total_unrealized_pnl(self, target_currency: str = "TWD", included_types: Optional[List[AssetType]] = None) -> float:
        """
        獲取總未實現損益（轉換為目標貨幣）
        
        Args:
            target_currency: 目標貨幣（預設為 TWD）
            included_types: 要包含的資產類型列表，如果為 None 則包含所有類型
        """
        return self.get_total_value(target_currency, included_types) - self.get_total_cost(target_currency, included_types)

    def get_total_realized_pnl(
        self, target_currency: str = "TWD", included_types: Optional[List[AssetType]] = None
    ) -> float:
        """已實現損益加總（換算為目標幣別）。"""
        total = 0.0
        for asset in self.assets.values():
            if included_types is not None and asset.asset_type not in included_types:
                continue
            curr = self._get_asset_currency(asset)
            r = asset.realized_pnl
            if target_currency == "TWD":
                total += self.currency_converter.convert_to_twd(r, curr)
            else:
                twd = self.currency_converter.convert_to_twd(r, curr)
                total += self.currency_converter.convert_from_twd(twd, target_currency)
        return total

    def get_daily_asset_snapshots(self) -> List[Dict[str, float]]:
        """取得每日資產快照，供 UI 畫趨勢圖。"""
        return self.db_manager.load_daily_asset_snapshots()

    def update_daily_asset_snapshots(self, progress_callback=None):
        """補齊缺漏日期，並更新今天的每日資產快照。"""
        def _progress(msg: str):
            if callable(progress_callback):
                progress_callback(msg)

        if not self.transactions:
            return

        first_tx_date = min(self._normalize_tx_date(t.date).date() for t in self.transactions)
        today = datetime.now().date()
        schema_version = self.db_manager.get_setting("daily_asset_snapshots_version")
        existing = set() if schema_version != "2" else set(self.db_manager.load_daily_asset_snapshot_dates())
        missing_dates = [
            first_tx_date + timedelta(days=i)
            for i in range((today - first_tx_date).days + 1)
            if first_tx_date + timedelta(days=i) not in existing or first_tx_date + timedelta(days=i) == today
        ]

        if not missing_dates:
            return

        price_cache: Dict[tuple[str, AssetType, date_type], Optional[float]] = {}
        fx_cache: Dict[tuple[str, date_type], float] = {}
        max_dates = len(missing_dates)
        for index, snapshot_date in enumerate(missing_dates, start=1):
            if index == 1 or index == max_dates or index % 10 == 0:
                _progress(f"補齊每日資產快照... ({index}/{max_dates})")
            values = self._calculate_snapshot_values(
                snapshot_date, price_cache=price_cache, fx_cache=fx_cache
            )
            self.db_manager.save_daily_asset_snapshot(
                snapshot_date,
                values["total_value_twd"],
                values["tw_stock_value_twd"],
                values["us_stock_value_twd"],
                values["hk_stock_value_twd"],
                values["fund_value_twd"],
                values["crypto_value_twd"],
                values["metal_value_twd"],
            )
        self.db_manager.set_setting("daily_asset_snapshots_version", "2")

    def _calculate_snapshot_values(
        self,
        snapshot_date: date_type,
        price_cache: Dict[tuple[str, AssetType, date_type], Optional[float]],
        fx_cache: Dict[tuple[str, date_type], float],
    ) -> Dict[str, float]:
        """計算指定日期收盤後的各類資產市值（TWD）。"""
        snapshot_transactions = [
            t for t in self.transactions
            if self._normalize_tx_date(t.date).date() <= snapshot_date
        ]
        assets = self._build_assets_from_transactions(snapshot_transactions, update_tracking=False)
        values = {
            "total_value_twd": 0.0,
            "tw_stock_value_twd": 0.0,
            "us_stock_value_twd": 0.0,
            "hk_stock_value_twd": 0.0,
            "fund_value_twd": 0.0,
            "crypto_value_twd": 0.0,
            "metal_value_twd": 0.0,
        }

        for asset in assets.values():
            if abs(asset.quantity) <= 1e-12:
                continue
            price = self._get_snapshot_price(asset, snapshot_date, price_cache)
            if price is None:
                price = asset.current_price or 0.0
            value = asset.quantity * price
            value_currency = "USD" if asset.asset_type in [AssetType.METAL, AssetType.CRYPTO] else self._get_asset_currency(asset)
            value_twd = self._convert_to_twd_on_date(value, value_currency, snapshot_date, fx_cache)
            values["total_value_twd"] += value_twd
            if asset.asset_type == AssetType.TAIWAN_STOCK:
                values["tw_stock_value_twd"] += value_twd
            elif asset.asset_type == AssetType.US_STOCK:
                values["us_stock_value_twd"] += value_twd
            elif asset.asset_type == AssetType.HK_STOCK:
                values["hk_stock_value_twd"] += value_twd
            elif asset.asset_type == AssetType.FUND:
                values["fund_value_twd"] += value_twd
            elif asset.asset_type == AssetType.CRYPTO:
                values["crypto_value_twd"] += value_twd
            elif asset.asset_type == AssetType.METAL:
                values["metal_value_twd"] += value_twd

        return values

    def _convert_to_twd_on_date(
        self,
        amount: float,
        currency: str,
        snapshot_date: date_type,
        fx_cache: Dict[tuple[str, date_type], float],
    ) -> float:
        if currency == "TWD":
            return amount
        cache_key = (currency, snapshot_date)
        if cache_key in fx_cache:
            return amount * fx_cache[cache_key]

        yahoo_symbol = "USDTWD=X" if currency == "USD" else "HKDTWD=X" if currency == "HKD" else None
        fallback = 32.0 if currency == "USD" else 4.1 if currency == "HKD" else 1.0
        rate = fallback
        if yahoo_symbol:
            close = self._get_yahoo_daily_close(yahoo_symbol, snapshot_date)
            if close is not None:
                rate = close
            elif currency == "USD":
                rate = self.currency_converter.get_usd_to_twd_rate()
            elif currency == "HKD":
                rate = self.currency_converter.get_hkd_to_twd_rate()
        fx_cache[cache_key] = rate
        return amount * rate

    def _get_snapshot_price(
        self,
        asset: Asset,
        snapshot_date: date_type,
        price_cache: Dict[tuple[str, AssetType, date_type], Optional[float]],
    ) -> Optional[float]:
        cache_key = (asset.symbol, asset.asset_type, snapshot_date)
        if cache_key in price_cache:
            return price_cache[cache_key]

        price = None
        try:
            if asset.asset_type in [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND]:
                adapter = StockPriceAdapter()
                yahoo_symbol = adapter._get_yahoo_symbol(asset.symbol, asset.asset_type)
                price = self._get_yahoo_daily_close(yahoo_symbol, snapshot_date)
                if price is None and asset.asset_type == AssetType.TAIWAN_STOCK and "." not in asset.symbol:
                    price = self._get_yahoo_daily_close(f"{asset.symbol}.TWO", snapshot_date)
            elif asset.asset_type == AssetType.METAL:
                adapter = GoldPriceAdapter()
                price = self._get_yahoo_daily_close(adapter._get_yahoo_symbol(asset.symbol), snapshot_date)
            elif asset.asset_type == AssetType.CRYPTO:
                price = self._get_yahoo_daily_close(f"{asset.symbol.upper()}-USD", snapshot_date)
        except Exception:
            price = None

        price_cache[cache_key] = price
        return price

    def _get_yahoo_daily_close(self, yahoo_symbol: str, snapshot_date: date_type) -> Optional[float]:
        """抓指定日期或最近前一個交易日的日收盤價。"""
        try:
            import yfinance as yf
            start = snapshot_date - timedelta(days=7)
            end = snapshot_date + timedelta(days=1)
            data = yf.Ticker(yahoo_symbol).history(start=start.isoformat(), end=end.isoformat(), interval="1d")
            if data.empty:
                return None
            if getattr(data.index, "tz", None) is not None:
                data.index = data.index.tz_convert(None)
            eligible = data[data.index.date <= snapshot_date]
            if eligible.empty:
                return None
            return float(eligible["Close"].iloc[-1])
        except Exception:
            return None

    def _get_asset_currency(self, asset: Asset) -> str:
        """獲取資產的貨幣（從交易記錄中推斷）"""
        # 查找該資產的第一筆交易記錄以確定貨幣
        for transaction in self.transactions:
            if transaction.symbol == asset.symbol and transaction.asset_type == asset.asset_type:
                return transaction.currency
        # 預設貨幣規則：
        # - 台股、基金、貴金屬（金屬）：台幣 (TWD)
        # - 美股、虛擬貨幣（Crypto）：美金 (USD)
        # - 港股：港幣 (HKD)
        if asset.asset_type == AssetType.US_STOCK or asset.asset_type == AssetType.CRYPTO:
            return "USD"
        elif asset.asset_type == AssetType.HK_STOCK:
            return "HKD"
        elif asset.asset_type == AssetType.TAIWAN_STOCK or asset.asset_type == AssetType.FUND or asset.asset_type == AssetType.METAL:
            return "TWD"
        return "TWD"
    
    def get_type_statistics(self, asset_type: AssetType) -> Dict[str, float]:
        """獲取特定資產類型的統計資訊"""
        assets = [a for a in self.assets.values() if a.asset_type == asset_type]
        total_unreal = sum(a.unrealized_pnl for a in assets)
        total_realized = sum(a.realized_pnl for a in assets)
        total_combined = sum(a.total_pnl for a in assets)
        sum_cost = sum(a.total_cost for a in assets)
        sum_buy = sum(a.total_buy_cash for a in assets)
        return {
            'count': len(assets),
            'total_value': sum(a.current_value for a in assets),
            'total_cost': sum_cost,
            'total_unrealized_pnl': total_unreal,
            'total_realized_pnl': total_realized,
            'total_pnl': total_combined,
            'total_pnl_percent': (total_unreal / sum_cost * 100) if sum_cost > 0 else 0.0,
            'total_return_percent': (total_combined / sum_buy * 100) if sum_buy > 0 else 0.0,
        }
    
    def delete_transaction(self, transaction_id: str):
        """刪除交易記錄並重新計算資產"""
        self.transactions = [t for t in self.transactions if t.id != transaction_id]
        self.db_manager.delete_transaction(transaction_id)
        self._recalculate_assets()
    
    def load_from_database(self):
        """從資料庫載入交易記錄"""
        self.transactions = self.db_manager.load_transactions()
        # 重新計算所有資產
        self._recalculate_assets()
    
    def _recalculate_assets(self):
        """重新計算所有資產（當交易被刪除時）"""
        self.realized_pnl_by_transaction_id = {}
        self.realized_cost_basis_by_transaction_id = {}
        self.buy_remaining_qty_by_transaction_id = {}
        self.buy_remaining_cost_basis_by_transaction_id = {}
        self.assets = self._build_assets_from_transactions(self.transactions, update_tracking=True)

    def _build_assets_from_transactions(
        self, transactions: List[Transaction], update_tracking: bool = False
    ) -> Dict[str, Asset]:
        """依交易清單建立資產狀態，不改動目前 PortfolioManager 狀態。"""
        ordered = sorted(
            transactions,
            key=lambda t: (
                self._normalize_tx_date(t.date),
                0 if t.transaction_type == TransactionType.BUY else 1,  # 同天固定先處理買入
                str(t.id),
            ),
        )
        fifo = self._compute_fifo_realized_by_asset(ordered)
        assets: Dict[str, Asset] = {}
        prev_assets = self.assets
        self.assets = assets
        if update_tracking:
            for _key, st in fifo.items():
                for tx_id, pnl in st.get("realized_pnl_by_sell_id", {}).items():
                    self.realized_pnl_by_transaction_id[tx_id] = float(pnl)
                for tx_id, cost_basis in st.get("cost_basis_by_sell_id", {}).items():
                    self.realized_cost_basis_by_transaction_id[tx_id] = float(cost_basis)
                for tx_id, rem_qty in st.get("buy_remaining_qty_by_buy_id", {}).items():
                    self.buy_remaining_qty_by_transaction_id[tx_id] = float(rem_qty)
                for tx_id, cost_basis in st.get("buy_remaining_cost_basis_by_buy_id", {}).items():
                    self.buy_remaining_cost_basis_by_transaction_id[tx_id] = float(cost_basis)

        try:
            for transaction in ordered:
                self._update_asset_from_transaction(transaction)
            for key, asset in self.assets.items():
                st = fifo.get(key, {})
                asset.realized_pnl = float(st.get("realized_pnl", 0.0))
                asset.total_buy_cash = float(st.get("total_buy_cash", 0.0))
            return assets
        finally:
            self.assets = prev_assets

    def _normalize_tx_date(self, d) -> datetime:
        """
        將交易日期統一成 datetime，避免 date 與 datetime 混在一起排序時丟 TypeError。
        """
        if isinstance(d, datetime):
            return d
        if isinstance(d, date_type):
            # date -> datetime（用 00:00:00）
            return datetime.combine(d, time_type.min)
        # 最保險的 fallback：嘗試把它解析成 datetime
        try:
            return datetime.fromisoformat(str(d))
        except Exception:
            # 若實在無法解析，全部推到同一個時間點（避免排序再爆）
            return datetime.fromtimestamp(0)

    def rebuild_holdings_preserve_prices(self):
        """
        重建持倉（含 FIFO 已實現損益、保留已賣出完的 lot，讓 UI 可展開）。
        同時盡量保留現有已抓到的 current_price / last_updated，避免刷新後價格變成 0。
        """
        price_cache = {}
        for key, asset in self.assets.items():
            price_cache[key] = (asset.current_price, asset.last_updated)

        # 重新計算資產/持倉
        self._recalculate_assets()

        # 重新套用價格快取（僅套用當前價格與時間，不影響持倉數量/成本）
        for key, asset in self.assets.items():
            if key not in price_cache:
                continue
            cached_price, cached_time = price_cache[key]
            asset.current_price = cached_price
            asset.last_updated = cached_time
            for pos in asset.positions:
                pos.current_price = cached_price
                pos.last_updated = cached_time
