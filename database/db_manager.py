"""資料庫管理器"""
import sqlite3
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from models.transaction import Transaction, TransactionType
from models.asset import AssetType


class DatabaseManager:
    """SQLite 資料庫管理器"""
    
    def __init__(self, db_path: str = "portfolio.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """初始化資料庫表結構"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 交易記錄表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                date TEXT NOT NULL,
                fee REAL DEFAULT 0.0,
                unit TEXT,
                currency TEXT DEFAULT 'TWD',
                notes TEXT
            )
        """)

        # App 設定（用來記住 UI 狀態，例如：總資產計算包含哪些資產類型）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # 手拉排序（每個資產類型可針對代號保存顯示順序）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asset_order (
                asset_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                sort_index INTEGER NOT NULL,
                PRIMARY KEY (asset_type, symbol)
            )
        """)
        
        # 如果表已存在但沒有 currency 欄位，則添加
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN currency TEXT DEFAULT 'TWD'")
        except sqlite3.OperationalError:
            pass  # 欄位已存在
        
        conn.commit()
        conn.close()

    def set_setting(self, key: str, value: str):
        """寫入設定值（字串）。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
        conn.close()

    def get_setting(self, key: str) -> Optional[str]:
        """讀取設定值（字串）。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def save_asset_order(self, asset_type: AssetType, symbols_in_order: List[str]):
        """保存某資產類型的手拉排序順序。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 清掉舊的順序，避免殘留（同 asset_type）
        cursor.execute("DELETE FROM asset_order WHERE asset_type = ?", (asset_type.value,))

        cursor.executemany(
            "INSERT INTO asset_order (asset_type, symbol, sort_index) VALUES (?, ?, ?)",
            [(asset_type.value, symbol, idx) for idx, symbol in enumerate(symbols_in_order)],
        )

        conn.commit()
        conn.close()

    def load_asset_order(self, asset_type: AssetType) -> List[str]:
        """載入某資產類型的手拉排序順序（回傳 symbol list）。"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT symbol FROM asset_order WHERE asset_type = ? ORDER BY sort_index ASC",
            (asset_type.value,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]
    
    def save_transaction(self, transaction: Transaction):
        """儲存交易記錄"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO transactions 
            (id, symbol, name, asset_type, transaction_type, quantity, price, date, fee, unit, currency, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            transaction.id,
            transaction.symbol,
            transaction.name,
            transaction.asset_type.value,
            transaction.transaction_type.value,
            transaction.quantity,
            transaction.price,
            transaction.date.isoformat(),
            transaction.fee,
            transaction.unit,
            transaction.currency,
            transaction.notes
        ))
        
        conn.commit()
        conn.close()
    
    def load_transactions(self) -> List[Transaction]:
        """載入所有交易記錄"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM transactions ORDER BY date")
        rows = cursor.fetchall()
        
        transactions = []
        for row in rows:
            # 處理舊資料（沒有 currency 欄位）
            currency = row[11] if len(row) > 11 else "TWD"
            
            # 處理舊的資產類型名稱（"金屬" -> "貴金屬"）
            asset_type_str = row[3]
            if asset_type_str == "金屬":
                asset_type_str = "貴金屬"
                # 更新數據庫中的舊數據
                cursor.execute(
                    "UPDATE transactions SET asset_type = ? WHERE id = ?",
                    ("貴金屬", row[0])
                )
            
            try:
                asset_type = AssetType(asset_type_str)
            except ValueError:
                # 如果仍然無法解析，使用預設值
                print(f"Warning: Unknown asset type '{asset_type_str}', using default")
                asset_type = AssetType.TAIWAN_STOCK
            
            transaction = Transaction(
                id=row[0],
                symbol=row[1],
                name=row[2],
                asset_type=asset_type,
                transaction_type=TransactionType(row[4]),
                quantity=row[5],
                price=row[6],
                date=datetime.fromisoformat(row[7]),
                fee=row[8],
                unit=row[9] if len(row) > 9 else None,
                currency=currency,
                notes=row[12] if len(row) > 12 else None
            )
            transactions.append(transaction)
        
        # 提交數據庫更新（如果有更新舊數據）
        conn.commit()
        conn.close()
        return transactions
    
    def delete_transaction(self, transaction_id: str):
        """刪除交易記錄"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        
        conn.commit()
        conn.close()
    
    def clear_all(self):
        """清空所有資料"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM transactions")
        
        conn.commit()
        conn.close()
