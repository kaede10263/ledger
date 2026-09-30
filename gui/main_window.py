"""主視窗"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import sys

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QDialog, QFormLayout, QLineEdit,
    QComboBox, QDoubleSpinBox, QDateEdit, QTextEdit, QLabel, QMessageBox,
    QHeaderView, QGroupBox, QTreeWidget, QTreeWidgetItem, QScrollArea,
    QFrame, QGridLayout, QListWidget, QListWidgetItem, QTabWidget, QMenu,
    QCheckBox, QAbstractItemView, QButtonGroup
)
from PySide6.QtCore import Qt, QDate, QTimer, QPoint, QObject, Signal, QThread
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QAction, QKeySequence, QShortcut
from shiboken6 import isValid

from portfolio_manager import PortfolioManager
from models.asset import AssetType
from models.transaction import Transaction, TransactionType
from utils.gold_converter import convert_from_grams, convert_to_grams
from adapters import StockPriceAdapter, CryptoPriceAdapter


class AssetTreeWidget(QTreeWidget):
    """支援手拉排序並可在 drop 後回呼保存順序的樹狀表格。"""

    def __init__(self, asset_type: AssetType, on_order_changed, parent=None):
        super().__init__(parent)
        self._asset_type = asset_type
        self._on_order_changed = on_order_changed

        # 只允許頂層 item 手拉排序（子項目跟著父項目走）
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event):
        super().dropEvent(event)
        if callable(self._on_order_changed):
            self._on_order_changed(self._asset_type)


class DailyAssetChart(QWidget):
    """簡易每日資產折線圖，不額外依賴圖表套件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self._scale = "day"
        self._visible_asset_types = set(AssetType)
        self._hover_x = None
        self._points = []
        self.setMouseTracking(True)
        self.setMinimumHeight(360)

    def set_data(self, data, scale=None):
        self._data = data or []
        if scale is not None:
            self._scale = scale
        self.update()

    def set_scale(self, scale):
        self._scale = scale
        self.update()

    def set_visible_asset_types(self, asset_types):
        self._visible_asset_types = set(asset_types or [])
        self.update()

    def mouseMoveEvent(self, event):
        self._hover_x = event.position().x()
        self.update()

    def leaveEvent(self, event):
        self._hover_x = None
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(18, 18, -18, -18)
        painter.fillRect(rect, QColor("#151a21"))

        if not self._data:
            painter.setPen(QColor("#93a4b7"))
            painter.drawText(rect, Qt.AlignCenter, "更新價格後會建立每日資產快照")
            return

        display_data = self._aggregate_data(self._limit_rows(self._data, self._scale), self._scale)
        if not display_data:
            return

        left = rect.left() + 72
        right = rect.right() - 22
        top = rect.top() + 20
        bottom = rect.bottom() - 46
        plot_w = max(1, right - left)
        plot_h = max(1, bottom - top)

        display_data = [self._row_with_visible_total(row) for row in display_data]
        series_defs = self._series_defs()
        all_values = [
            float(item.get(key, 0.0) or 0.0)
            for item in display_data
            for key, _label, _color in series_defs
        ]
        if not all_values:
            painter.setPen(QColor("#93a4b7"))
            painter.drawText(rect, Qt.AlignCenter, "請勾選至少一種資產類型")
            return
        max_v = max(all_values) if all_values else 0.0
        min_v = min(all_values) if all_values else 0.0
        if max_v <= min_v:
            max_v = min_v + 1.0

        painter.setPen(QPen(QColor("#2a313b"), 1))
        for i in range(5):
            y = top + (plot_h * i / 4)
            painter.drawLine(left, int(y), right, int(y))
            value = max_v - ((max_v - min_v) * i / 4)
            painter.setPen(QColor("#93a4b7"))
            painter.drawText(rect.left(), int(y) - 8, 64, 18, Qt.AlignRight, self._format_money(value))
            painter.setPen(QPen(QColor("#2a313b"), 1))

        count = len(display_data)

        def point_at(row_index, value):
            x = left if count == 1 else left + (plot_w * row_index / (count - 1))
            y = bottom - ((float(value or 0.0) - min_v) / (max_v - min_v) * plot_h)
            return int(x), int(y)

        x_positions = []
        for key, label, color in series_defs:
            painter.setPen(QPen(color, 2))
            last = None
            for i, item in enumerate(display_data):
                pt = point_at(i, item.get(key, 0.0))
                if key == series_defs[0][0]:
                    x_positions.append(pt[0])
                if last is not None:
                    painter.drawLine(last[0], last[1], pt[0], pt[1])
                last = pt
        self._points = list(zip(x_positions, display_data))

        painter.setPen(QColor("#93a4b7"))
        first_date = str(display_data[0].get("date", ""))
        last_date = str(display_data[-1].get("date", ""))
        painter.drawText(left, bottom + 20, 120, 20, Qt.AlignLeft, first_date)
        painter.drawText(right - 120, bottom + 20, 120, 20, Qt.AlignRight, last_date)

        legend_x = left
        legend_y = rect.top()
        for _key, label, color in series_defs:
            painter.setPen(QPen(color, 3))
            painter.drawLine(legend_x, legend_y + 8, legend_x + 20, legend_y + 8)
            painter.setPen(QColor("#d5dee9"))
            painter.drawText(legend_x + 26, legend_y, 70, 18, Qt.AlignLeft, label)
            legend_x += 92

        if self._hover_x is not None and self._points:
            x, row = min(self._points, key=lambda p: abs(p[0] - self._hover_x))
            if left <= x <= right:
                painter.setPen(QPen(QColor("#6d7b8c"), 1))
                painter.drawLine(x, top, x, bottom)
                self._draw_hover_box(painter, rect, x, top, row, series_defs)

    def _draw_hover_box(self, painter, rect, x, top, row, series_defs):
        lines = [str(row.get("date", ""))]
        for key, label, _color in series_defs:
            lines.append(f"{label}  NT$ {float(row.get(key, 0.0) or 0.0):,.0f}")
        box_w = 210
        box_h = 22 + 20 * len(series_defs)
        box_x = x + 12
        if box_x + box_w > rect.right():
            box_x = x - box_w - 12
        box_y = top + 8
        painter.setPen(QPen(QColor("#3a4452"), 1))
        painter.setBrush(QColor(24, 30, 39, 235))
        painter.drawRoundedRect(box_x, box_y, box_w, box_h, 6, 6)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor("#d5dee9"))
        painter.drawText(box_x + 10, box_y + 18, lines[0])
        y = box_y + 40
        for index, (key, label, color) in enumerate(series_defs):
            painter.setPen(color)
            painter.drawText(box_x + 10, y, label)
            painter.setPen(QColor("#d5dee9"))
            painter.drawText(box_x + 74, y, f"NT$ {float(row.get(key, 0.0) or 0.0):,.0f}")
            y += 20

    def _series_defs(self):
        defs = [("visible_total_value_twd", "總資產", QColor("#58d6a3"))]
        asset_defs = [
            (AssetType.TAIWAN_STOCK, "tw_stock_value_twd", "台股", QColor("#f0b84a")),
            (AssetType.US_STOCK, "us_stock_value_twd", "美股", QColor("#cb7cff")),
            (AssetType.HK_STOCK, "hk_stock_value_twd", "港股", QColor("#55c7ff")),
            (AssetType.FUND, "fund_value_twd", "基金", QColor("#ff7ab6")),
            (AssetType.CRYPTO, "crypto_value_twd", "虛擬貨幣", QColor("#33d6d0")),
            (AssetType.METAL, "metal_value_twd", "貴金屬", QColor("#ffd166")),
        ]
        for asset_type, key, label, color in asset_defs:
            if asset_type in self._visible_asset_types:
                defs.append((key, label, color))
        return defs

    def _row_with_visible_total(self, row):
        fields = {
            AssetType.TAIWAN_STOCK: "tw_stock_value_twd",
            AssetType.US_STOCK: "us_stock_value_twd",
            AssetType.HK_STOCK: "hk_stock_value_twd",
            AssetType.FUND: "fund_value_twd",
            AssetType.CRYPTO: "crypto_value_twd",
            AssetType.METAL: "metal_value_twd",
        }
        total = 0.0
        for asset_type, key in fields.items():
            if asset_type in self._visible_asset_types:
                total += float(row.get(key, 0.0) or 0.0)
        copied = dict(row)
        copied["visible_total_value_twd"] = total
        return copied

    def _limit_rows(self, rows, scale):
        if not rows:
            return []
        days_by_scale = {
            "day": 92,
            "week": 370,
            "month": 365 * 3,
            "quarter": 365 * 5,
            "half": 365 * 6,
            "year": 365 * 10,
        }
        days = days_by_scale.get(scale)
        if not days:
            return rows
        try:
            last = datetime.fromisoformat(str(rows[-1].get("date"))).date()
        except Exception:
            return rows
        start = last - timedelta(days=days)
        limited = []
        for row in rows:
            try:
                dt = datetime.fromisoformat(str(row.get("date"))).date()
            except Exception:
                continue
            if dt >= start:
                limited.append(row)
        return limited or rows[-1:]

    def _aggregate_data(self, rows, scale):
        if scale == "day":
            return rows
        grouped = {}
        order = []
        for row in rows:
            try:
                dt = datetime.fromisoformat(str(row.get("date"))).date()
            except Exception:
                continue
            key = self._bucket_key(dt, scale)
            if key not in grouped:
                order.append(key)
            grouped[key] = row
        return [grouped[key] for key in order]

    def _bucket_key(self, dt, scale):
        if scale == "week":
            iso = dt.isocalendar()
            return (iso.year, iso.week)
        if scale == "month":
            return (dt.year, dt.month)
        if scale == "quarter":
            return (dt.year, (dt.month - 1) // 3)
        if scale == "half":
            return (dt.year, 0 if dt.month <= 6 else 1)
        if scale == "year":
            return (dt.year,)
        return dt.isoformat()

    def _format_money(self, value):
        abs_v = abs(value)
        if abs_v >= 100000000:
            return f"{value / 100000000:.1f}億"
        if abs_v >= 10000:
            return f"{value / 10000:.1f}萬"
        return f"{value:.0f}"


class TransactionDialog(QDialog):
    """交易輸入對話框"""
    
    def __init__(
        self,
        parent=None,
        transaction: Optional[Transaction] = None,
        default_asset_type: Optional[AssetType] = None,
    ):
        super().__init__(parent)
        self._editing_transaction_id: Optional[str] = None
        self.setWindowTitle("新增交易" if transaction is None else "編輯交易")
        self.setMinimumWidth(400)
        self.setup_ui()

        # 預設資產類型（用於「新增」時依目前頁籤帶入）
        if transaction is None and default_asset_type is not None:
            try:
                self.asset_type_combo.setCurrentIndex(list(AssetType).index(default_asset_type))
            except ValueError:
                self.asset_type_combo.setCurrentIndex(0)
            self._on_asset_type_changed()

        if transaction is not None:
            self.set_transaction(transaction)
    
    def setup_ui(self):
        # 整體版面：分區，避免表單太單調
        root = QVBoxLayout()
        root.setSpacing(12)
        root.setContentsMargins(14, 14, 14, 14)

        basic_group = QGroupBox("基本資料")
        basic_layout = QFormLayout()
        basic_layout.setLabelAlignment(Qt.AlignRight)
        basic_layout.setFormAlignment(Qt.AlignTop)
        basic_group.setLayout(basic_layout)
        
        # 資產類型
        self.asset_type_combo = QComboBox()
        self.asset_type_combo.addItems([at.value for at in AssetType])
        basic_layout.addRow("資產類型:", self.asset_type_combo)
        
        # 代號（一般資產使用輸入框，金屬使用下拉選單）
        self.symbol_edit = QLineEdit()
        self.symbol_edit.setPlaceholderText("例：2330 / AAPL / VTI / BTC-USD")
        self.symbol_edit.editingFinished.connect(self._on_symbol_changed)
        self.symbol_combo = QComboBox()
        self.symbol_combo.addItems(["黃金", "白銀", "白金", "鈀金"])
        self.symbol_combo.setVisible(False)  # 預設隱藏
        self.symbol_combo.currentIndexChanged.connect(self._on_metal_type_changed)
        symbol_layout = QHBoxLayout()
        symbol_layout.addWidget(self.symbol_edit)
        symbol_layout.addWidget(self.symbol_combo)
        basic_layout.addRow("代號:", symbol_layout)
        
        # 名稱（一般資產使用輸入框，金屬使用下拉選單）
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("可輸入或由系統自動帶入")
        self.name_combo = QComboBox()
        self.name_combo.addItems(["黃金 (Gold)", "白銀 (Silver)", "白金 (Platinum)", "鈀金 (Palladium)"])
        self.name_combo.setVisible(False)  # 預設隱藏
        name_layout = QHBoxLayout()
        name_layout.addWidget(self.name_edit)
        name_layout.addWidget(self.name_combo)
        basic_layout.addRow("名稱:", name_layout)
        
        # 用於獲取股票和加密貨幣名稱的適配器
        self.stock_adapter = StockPriceAdapter()
        self.crypto_adapter = CryptoPriceAdapter()

        trade_group = QGroupBox("交易資料")
        trade_layout = QFormLayout()
        trade_layout.setLabelAlignment(Qt.AlignRight)
        trade_layout.setFormAlignment(Qt.AlignTop)
        trade_group.setLayout(trade_layout)
        
        # 交易類型
        self.transaction_type_combo = QComboBox()
        self.transaction_type_combo.addItems([tt.value for tt in TransactionType])
        trade_layout.addRow("交易類型:", self.transaction_type_combo)
        
        # 數量
        quantity_layout = QHBoxLayout()
        self.quantity_spin = QDoubleSpinBox()
        self.quantity_spin.setMinimum(0.0001)
        self.quantity_spin.setMaximum(999999999)
        self.quantity_spin.setDecimals(4)
        
        # 單位選擇（僅金屬顯示）
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["錢", "盎司", "g", "兩"])  # 預設使用「錢」
        self.unit_combo.setVisible(False)  # 預設隱藏
        
        quantity_layout.addWidget(self.quantity_spin)
        quantity_layout.addWidget(self.unit_combo)
        trade_layout.addRow("數量:", quantity_layout)
        
        # 監聽資產類型變化
        self.asset_type_combo.currentIndexChanged.connect(self._on_asset_type_changed)
        
        # 貨幣選擇
        currency_layout = QHBoxLayout()
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(["TWD (台幣)", "USD (美金)", "HKD (港幣)"])
        currency_layout.addWidget(QLabel("計價貨幣:"))
        currency_layout.addWidget(self.currency_combo)
        currency_layout.addStretch()
        trade_layout.addRow(currency_layout)
        
        # 價格（帶單位標籤，字體放大一倍）
        price_label_text = QLabel("價格:")
        price_label_font = QFont()
        price_label_font.setPointSize(20)
        price_label_text.setFont(price_label_font)
        price_layout = QHBoxLayout()
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setMinimum(0.01)
        self.price_spin.setMaximum(999999999)
        self.price_spin.setDecimals(2)
        price_spin_font = QFont()
        price_spin_font.setPointSize(18)
        self.price_spin.setFont(price_spin_font)
        self.price_label = QLabel("TWD")  # 預設顯示台幣
        self.price_label.setMinimumWidth(100)
        price_unit_font = QFont()
        price_unit_font.setPointSize(18)
        self.price_label.setFont(price_unit_font)
        price_layout.addWidget(self.price_spin)
        price_layout.addWidget(self.price_label)
        trade_layout.addRow(price_label_text, price_layout)
        
        # 監聽貨幣變化
        self.currency_combo.currentIndexChanged.connect(self._on_currency_changed)
        
        # 日期
        self.date_edit = QDateEdit()
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        trade_layout.addRow("交易日期:", self.date_edit)
        
        # 手續費（帶單位標籤）
        fee_layout = QHBoxLayout()
        self.fee_spin = QDoubleSpinBox()
        self.fee_spin.setMinimum(0)
        self.fee_spin.setMaximum(999999)
        self.fee_spin.setDecimals(2)
        self.fee_label = QLabel("TWD")  # 預設顯示台幣
        self.fee_label.setMinimumWidth(50)
        fee_layout.addWidget(self.fee_spin)
        fee_layout.addWidget(self.fee_label)
        trade_layout.addRow("手續費:", fee_layout)
        
        # 備註
        notes_group = QGroupBox("備註")
        notes_layout = QVBoxLayout()
        notes_group.setLayout(notes_layout)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("可選填：策略/原因/券商/手續費明細…")
        self.notes_edit.setMaximumHeight(90)
        notes_layout.addWidget(self.notes_edit)
        
        # 按鈕
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("確定")
        self.cancel_button = QPushButton("取消")
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        # 簡單驗證：避免空白送出（非金屬時代號/名稱必填）
        self._required_hint = QLabel("")
        self._required_hint.setStyleSheet("color: #b00020;")

        root.addWidget(self._required_hint)
        root.addWidget(basic_group)
        root.addWidget(trade_group)
        root.addWidget(notes_group)
        root.addLayout(button_layout)
        self.setLayout(root)

        self.symbol_edit.textChanged.connect(self._validate_required)
        self.name_edit.textChanged.connect(self._validate_required)
        self.asset_type_combo.currentIndexChanged.connect(self._validate_required)
        self._validate_required()

        # 初始焦點
        self.symbol_edit.setFocus()

    def _validate_required(self):
        asset_type = AssetType(list(AssetType)[self.asset_type_combo.currentIndex()])
        if asset_type == AssetType.METAL:
            self.ok_button.setEnabled(True)
            self._required_hint.setText("")
            return
        sym_ok = bool(self.symbol_edit.text().strip())
        name_ok = bool(self.name_edit.text().strip())
        ok = sym_ok and name_ok
        self.ok_button.setEnabled(ok)
        self._required_hint.setText("" if ok else "提示：代號與名稱為必填（輸入代號後可自動帶入名稱）")
    
    def _on_asset_type_changed(self):
        """當資產類型改變時，顯示/隱藏單位選擇並設定預設貨幣"""
        asset_type_index = self.asset_type_combo.currentIndex()
        asset_type = AssetType(list(AssetType)[asset_type_index])
        
        # 顯示/隱藏單位選擇和金屬類型下拉選單
        if asset_type == AssetType.METAL:
            self.unit_combo.setVisible(True)
            # 金屬：預設使用「錢」作為單位
            self.unit_combo.setCurrentText("錢")
            # 金屬：顯示下拉選單，隱藏輸入框
            self.symbol_edit.setVisible(False)
            self.symbol_combo.setVisible(True)
            self.name_edit.setVisible(False)
            self.name_combo.setVisible(True)
            # 自動選擇第一個金屬類型
            self._on_metal_type_changed()
        else:
            self.unit_combo.setVisible(False)
            # 一般資產：顯示輸入框，隱藏下拉選單
            self.symbol_edit.setVisible(True)
            self.symbol_combo.setVisible(False)
            self.name_edit.setVisible(True)
            self.name_combo.setVisible(False)
        
        # 根據資產類型自動設定預設貨幣
        # 台股、基金、貴金屬（金屬）：台幣 (TWD)
        # 美股、虛擬貨幣（Crypto）：美金 (USD)
        # 港股：港幣 (HKD)
        if asset_type in [AssetType.TAIWAN_STOCK, AssetType.FUND, AssetType.METAL]:
            self.currency_combo.setCurrentIndex(0)  # TWD (台幣)
        elif asset_type in [AssetType.US_STOCK, AssetType.CRYPTO]:
            self.currency_combo.setCurrentIndex(1)  # USD (美金)
        elif asset_type == AssetType.HK_STOCK:
            self.currency_combo.setCurrentIndex(2)  # HKD (港幣)
    
    def _on_metal_type_changed(self):
        """當金屬類型改變時，自動填充代號和名稱"""
        metal_type_index = self.symbol_combo.currentIndex()
        metal_types = {
            0: ("黃金", "黃金 (Gold)", "GC=F"),  # 黃金
            1: ("白銀", "白銀 (Silver)", "SI=F"),  # 白銀
            2: ("白金", "白金 (Platinum)", "PL=F"),  # 白金
            3: ("鈀金", "鈀金 (Palladium)", "PA=F")  # 鈀金
        }
        
        if metal_type_index in metal_types:
            symbol, name, yahoo_symbol = metal_types[metal_type_index]
            # 更新名稱下拉選單
            self.name_combo.setCurrentIndex(metal_type_index)
    
    def _on_currency_changed(self):
        """當貨幣選擇改變時，更新價格和手續費的單位標籤"""
        currency_map = {0: "TWD", 1: "USD", 2: "HKD"}
        currency = currency_map.get(self.currency_combo.currentIndex(), "TWD")
        
        self.price_label.setText(currency)
        self.fee_label.setText(currency)
    
    def _on_symbol_changed(self):
        """當代號輸入完成時，自動獲取股票名稱"""
        symbol = self.symbol_edit.text().strip()
        if not symbol:
            return
        
        asset_type_index = self.asset_type_combo.currentIndex()
        asset_type = AssetType(list(AssetType)[asset_type_index])
        
        # 對台股、美股、港股、基金自動填充名稱
        if asset_type in [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND]:
            if self.stock_adapter.supports(asset_type):
                name = self.stock_adapter.get_stock_name(symbol, asset_type)
                if name:
                    self.name_edit.setText(name)
        # 對加密貨幣自動填充名稱
        elif asset_type == AssetType.CRYPTO:
            name = self.crypto_adapter.get_crypto_name(symbol)
            if name:
                self.name_edit.setText(name)
    
    def get_transaction(self) -> Optional[Transaction]:
        """獲取輸入的交易資料"""
        if self.exec() == QDialog.Accepted:
            import uuid
            asset_type = AssetType(list(AssetType)[self.asset_type_combo.currentIndex()])
            transaction_type = TransactionType(list(TransactionType)[self.transaction_type_combo.currentIndex()])
            
            unit = None
            if asset_type == AssetType.METAL:
                unit = self.unit_combo.currentText()
            
            # 獲取選擇的貨幣
            currency_map = {0: "TWD", 1: "USD", 2: "HKD"}
            currency = currency_map.get(self.currency_combo.currentIndex(), "TWD")
            
            # 獲取代號和名稱（根據資產類型選擇輸入框或下拉選單）
            if asset_type == AssetType.METAL:
                symbol = self.symbol_combo.currentText()
                name = self.name_combo.currentText()
            else:
                symbol = self.symbol_edit.text().strip()
                name = self.name_edit.text().strip()
            
            tx_id = self._editing_transaction_id or str(uuid.uuid4())
            return Transaction(
                id=tx_id,
                symbol=symbol,
                name=name,
                asset_type=asset_type,
                transaction_type=transaction_type,
                quantity=self.quantity_spin.value(),
                price=self.price_spin.value(),
                date=self.date_edit.date().toPython(),
                fee=self.fee_spin.value(),
                unit=unit,
                currency=currency,
                notes=self.notes_edit.toPlainText().strip() or None
            )
        return None

    def set_transaction(self, transaction: Transaction):
        """將既有交易資料帶入 UI（用於編輯）。"""
        self._editing_transaction_id = transaction.id

        # 資產類型
        try:
            self.asset_type_combo.setCurrentIndex(list(AssetType).index(transaction.asset_type))
        except ValueError:
            self.asset_type_combo.setCurrentIndex(0)
        self._on_asset_type_changed()

        # 交易類型
        try:
            self.transaction_type_combo.setCurrentIndex(list(TransactionType).index(transaction.transaction_type))
        except ValueError:
            self.transaction_type_combo.setCurrentIndex(0)

        # 貨幣
        currency_index_map = {"TWD": 0, "USD": 1, "HKD": 2}
        self.currency_combo.setCurrentIndex(currency_index_map.get(transaction.currency, 0))
        self._on_currency_changed()

        # 代號 / 名稱（依資產類型）
        if transaction.asset_type == AssetType.METAL:
            # 金屬用下拉（依照 symbol 選擇）
            metal_map = {"黃金": 0, "白銀": 1, "白金": 2, "鈀金": 3}
            idx = metal_map.get(transaction.symbol, 0)
            self.symbol_combo.setCurrentIndex(idx)
            self.name_combo.setCurrentIndex(idx)
            self._on_metal_type_changed()
            if transaction.unit:
                self.unit_combo.setCurrentText(transaction.unit)
        else:
            self.symbol_edit.setText(transaction.symbol)
            self.name_edit.setText(transaction.name)

        # 數值
        self.quantity_spin.setValue(transaction.quantity)
        self.price_spin.setValue(transaction.price)
        self.fee_spin.setValue(transaction.fee)
        self.date_edit.setDate(QDate(transaction.date.year, transaction.date.month, transaction.date.day))
        self.notes_edit.setPlainText(transaction.notes or "")

class MainWindow(QMainWindow):
    """主視窗"""
    
    def __init__(self):
        super().__init__()
        self.portfolio_manager = PortfolioManager()
        self.setWindowTitle("Personal Portfolio Dashboard")
        self.setMinimumSize(1200, 800)
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "golden_ui_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self._history_scale = "day"
        # 儲存每個資產類型的排序設定
        self.sort_settings = {
            asset_type: {'key': 'value', 'order': 'desc'}
            for asset_type in [
                AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK,
                AssetType.FUND, AssetType.CRYPTO, AssetType.METAL
            ]
        }
        # 手拉排序（從 DB 載入）
        self.manual_order = {}  # {AssetType: [symbol, ...]}
        self.setup_ui()
        self._load_ui_settings()
        self.setup_timer()
        # 啟動時更新價格（在背景執行，避免阻塞 UI）
        QTimer.singleShot(1000, self.refresh_prices)

    def _load_ui_settings(self):
        """載入 UI 設定：總資產計算勾選 + 手拉排序。"""
        # checkbox 設定
        raw = self.portfolio_manager.db_manager.get_setting("included_asset_types")
        if raw:
            included = set([s for s in raw.split(",") if s])
            for at, cb in self.asset_type_checkboxes.items():
                cb.blockSignals(True)
                cb.setChecked(at.value in included)
                cb.blockSignals(False)

        hide_zero = self.portfolio_manager.db_manager.get_setting("hide_zero_quantity_assets")
        if hasattr(self, "hide_zero_quantity_checkbox") and hide_zero is not None:
            self.hide_zero_quantity_checkbox.blockSignals(True)
            self.hide_zero_quantity_checkbox.setChecked(hide_zero == "1")
            self.hide_zero_quantity_checkbox.blockSignals(False)

        # 手拉排序設定
        for at in self.asset_sections.keys():
            self.manual_order[at] = self.portfolio_manager.db_manager.load_asset_order(at)

    def _save_included_types_setting(self):
        included = [
            at.value for at, cb in self.asset_type_checkboxes.items()
            if cb.isChecked()
        ]
        self.portfolio_manager.db_manager.set_setting("included_asset_types", ",".join(included))

    def _save_hide_zero_setting(self):
        value = "1" if self.hide_zero_quantity_checkbox.isChecked() else "0"
        self.portfolio_manager.db_manager.set_setting("hide_zero_quantity_assets", value)

    def _on_manual_order_changed(self, asset_type: AssetType):
        """當手拉排序發生變化時，將順序保存到 DB。"""
        section = self.asset_sections.get(asset_type)
        if not section:
            return
        table = section.table

        symbols = []
        for i in range(table.topLevelItemCount()):
            item = table.topLevelItem(i)
            asset = item.data(0, Qt.UserRole)
            if asset is None:
                continue
            symbols.append(asset.symbol)

        self.manual_order[asset_type] = symbols
        self.sort_settings.pop(asset_type, None)
        self.portfolio_manager.db_manager.save_asset_order(asset_type, symbols)
    
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)
        central_widget.setLayout(layout)
        central_widget.setStyleSheet("""
            QWidget {
                background: #f4f7fb;
                color: #1f2937;
                font-family: "Microsoft JhengHei UI", "Microsoft JhengHei", Arial;
            }
            QPushButton {
                background: #ffffff;
                color: #243447;
                border: 1px solid #ccd6e0;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #eef5ff;
                border-color: #7aa7df;
            }
            QPushButton:pressed {
                background: #dcecff;
            }
            QPushButton:disabled {
                color: #8a97a6;
                background: #edf1f5;
            }
            QCheckBox {
                spacing: 6px;
            }
        """)
        
        # 總覽區塊：壓低高度，保留主要數字與篩選器
        self.total_card = QFrame()
        self.total_card.setObjectName("summaryPanel")
        self.total_card.setStyleSheet("""
            QFrame#summaryPanel {
                background: #ffffff;
                border: 1px solid #d8e0ea;
                border-radius: 8px;
            }
        """)
        total_layout = QVBoxLayout()
        self.total_card.setLayout(total_layout)
        total_layout.setContentsMargins(16, 12, 16, 12)
        total_layout.setSpacing(10)
        
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        title_label = QLabel("總資產")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #14213d;")
        header_layout.addWidget(title_label)
        
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setSpacing(10)
        checkbox_font = QFont()
        checkbox_font.setPointSize(9)
        self.asset_type_checkboxes = {}
        asset_type_labels = {
            AssetType.TAIWAN_STOCK: "台股",
            AssetType.US_STOCK: "美股",
            AssetType.HK_STOCK: "港股",
            AssetType.FUND: "基金",
            AssetType.CRYPTO: "虛擬貨幣",
            AssetType.METAL: "貴金屬"
        }
        for asset_type, label in asset_type_labels.items():
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)  # 預設全部選中
            checkbox.setFont(checkbox_font)
            checkbox.setStyleSheet("color: #506070;")
            checkbox.stateChanged.connect(self._on_asset_type_checkbox_changed)
            self.asset_type_checkboxes[asset_type] = checkbox
            checkbox_layout.addWidget(checkbox)
        checkbox_layout.addStretch()
        header_layout.addLayout(checkbox_layout, 1)
        total_layout.addLayout(header_layout)
        
        metric_layout = QHBoxLayout()
        metric_layout.setSpacing(10)
        self.total_value_label = self._create_metric_card(metric_layout, "總市值", "NT$ 0.00", accent=True)
        self.total_cost_label = self._create_metric_card(metric_layout, "總成本", "NT$ 0.00")
        self.total_pnl_label = self._create_metric_card(metric_layout, "未實現損益", "NT$ 0.00 (0.00%)")
        self.total_realized_label = self._create_metric_card(metric_layout, "已實現損益", "NT$ 0.00")
        self.total_combined_pnl_label = self._create_metric_card(metric_layout, "總損益", "NT$ 0.00")
        total_layout.addLayout(metric_layout)
        
        layout.addWidget(self.total_card)
        
        # 按鈕區
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        self.add_transaction_btn = QPushButton("新增交易")
        self.refresh_btn = QPushButton("更新價格")
        self.hide_zero_quantity_checkbox = QCheckBox("隱藏數量 0")
        self.hide_zero_quantity_checkbox.setStyleSheet("color: #506070; padding-left: 8px;")
        self.hide_zero_quantity_checkbox.stateChanged.connect(self._on_hide_zero_quantity_changed)
        self.refresh_status_label = QLabel("")
        self.refresh_status_label.setStyleSheet("color: #5c6f82; padding-left: 8px;")
        self.add_transaction_btn.clicked.connect(self.add_transaction)
        self.refresh_btn.clicked.connect(self.refresh_prices)
        button_layout.addWidget(self.add_transaction_btn)
        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.hide_zero_quantity_checkbox)
        button_layout.addWidget(self.refresh_status_label, 1)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        # 快捷鍵
        # - F5：刷新/更新價格
        # - F1：新增（新增交易）
        self._refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self._refresh_shortcut.activated.connect(self.refresh_prices)
        self._add_shortcut = QShortcut(QKeySequence("F1"), self)
        self._add_shortcut.activated.connect(self.add_transaction)
        
        # 使用標籤頁（Tab）切換不同資產類型
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setMovable(False)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #d8e0ea;
                border-radius: 8px;
                background-color: white;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #e8eef5;
                color: #4b5c6f;
                padding: 8px 18px;
                margin-right: 3px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: white;
                color: #1f5f99;
                border-bottom: 2px solid #1f8a70;
            }
            QTabBar::tab:hover {
                background-color: #f4f8fc;
            }
        """)
        
        # 為每種資產類型創建標籤頁
        self.asset_sections = {}
        asset_types = [AssetType.TAIWAN_STOCK, AssetType.US_STOCK, AssetType.HK_STOCK, AssetType.FUND, 
                      AssetType.CRYPTO, AssetType.METAL]
        
        for asset_type in asset_types:
            section = self._create_asset_section(asset_type)
            self.asset_sections[asset_type] = section
            self.tab_widget.addTab(section, asset_type.value)

        self.history_tab = self._create_history_section()
        self.tab_widget.addTab(self.history_tab, "資產趨勢")
        
        layout.addWidget(self.tab_widget)
        
        # 更新顯示
        self.refresh_table()

    def _create_metric_card(self, parent_layout: QHBoxLayout, title: str, value: str, accent: bool = False) -> QLabel:
        card = QFrame()
        card.setObjectName("metricCard")
        card.setStyleSheet("""
            QFrame#metricCard {
                background: #f8fafc;
                border: 1px solid #e1e8ef;
                border-radius: 8px;
            }
        """)
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(2)
        card.setLayout(card_layout)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #6b7c8f; font-size: 9pt;")
        card_layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        value_font = QFont()
        value_font.setPointSize(12 if not accent else 14)
        value_font.setBold(True)
        value_label.setFont(value_font)
        value_label.setStyleSheet("color: #14213d;")
        card_layout.addWidget(value_label)

        parent_layout.addWidget(card, 1)
        return value_label

    def _create_history_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        container.setLayout(layout)

        header = QLabel("歷史資產增長圖")
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet("color: #14213d;")
        layout.addWidget(header)

        chart_shell = QFrame()
        chart_shell.setObjectName("chartShell")
        chart_shell.setStyleSheet("""
            QFrame#chartShell {
                background: #151a21;
                border: 1px solid #2a313b;
                border-radius: 8px;
            }
        """)
        chart_layout = QVBoxLayout()
        chart_layout.setContentsMargins(18, 14, 18, 18)
        chart_layout.setSpacing(10)
        chart_shell.setLayout(chart_layout)

        chart_top_layout = QHBoxLayout()
        chart_top_layout.setSpacing(10)

        scale_layout = QHBoxLayout()
        scale_layout.setSpacing(2)
        self.history_scale_group = QButtonGroup(self)
        self.history_scale_group.setExclusive(True)
        scale_options = [
            ("day", "每日"),
            ("week", "星期"),
            ("month", "月"),
            ("quarter", "3月"),
            ("half", "半年"),
            ("year", "年"),
        ]
        for scale, text in scale_options:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setMinimumWidth(48)
            btn.setProperty("scale", scale)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #93a4b7;
                    border: none;
                    border-radius: 4px;
                    padding: 5px 8px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #202733;
                    color: #d5dee9;
                }
                QPushButton:checked {
                    background: #2b3543;
                    color: #ffffff;
                }
            """)
            if scale == self._history_scale:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, s=scale: self._on_history_scale_changed(s))
            self.history_scale_group.addButton(btn)
            scale_layout.addWidget(btn)
        chart_top_layout.addLayout(scale_layout)
        chart_top_layout.addStretch()
        chart_layout.addLayout(chart_top_layout)

        self.history_chart = DailyAssetChart()
        chart_layout.addWidget(self.history_chart, 1)

        layout.addWidget(chart_shell, 1)
        return container

    def _on_history_scale_changed(self, scale):
        self._history_scale = scale
        if hasattr(self, "history_chart"):
            self.history_chart.set_scale(scale)
        self._refresh_history_chart()
    
    def setup_timer(self):
        """設定自動更新計時器（每5分鐘更新一次價格）"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_prices)
        self.timer.start(300000)  # 5分鐘
    
    def add_transaction(self):
        """新增交易"""
        current_widget = self.tab_widget.currentWidget()
        default_asset_type = getattr(current_widget, "asset_type", None)
        dialog = TransactionDialog(self, default_asset_type=default_asset_type)
        transaction = dialog.get_transaction()
        
        if transaction:
            if not transaction.symbol or not transaction.name:
                QMessageBox.warning(self, "錯誤", "請輸入代號和名稱")
                return
            
            self.portfolio_manager.add_transaction(transaction)
            self.refresh_prices()
            self.refresh_table()
            QMessageBox.information(self, "成功", "交易已新增")
    
    def refresh_prices(self):
        """更新價格"""
        thread = getattr(self, "_refresh_thread", None)
        if thread is not None:
            if not isValid(thread):
                self._refresh_thread = None
            else:
                try:
                    if thread.isRunning():
                        return
                except RuntimeError:
                    self._refresh_thread = None

        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("更新中...")
        self._set_refresh_status("準備更新...")

        class _RefreshWorker(QObject):
            status = Signal(str)
            finished = Signal()
            error = Signal(str)

            def __init__(self, pm: PortfolioManager):
                super().__init__()
                self._pm = pm

            def run(self):
                try:
                    self.status.emit("讀取 SQL（交易/資產）...")
                    self._pm.load_from_database()
                    self.status.emit("開始更新價格...")
                    self._pm.update_prices(progress_callback=lambda m: self.status.emit(m))
                    self.finished.emit()
                except Exception as e:
                    self.error.emit(str(e))

        self._refresh_thread = QThread(self)
        self._refresh_worker = _RefreshWorker(self.portfolio_manager)
        self._refresh_worker.moveToThread(self._refresh_thread)

        self._refresh_thread.started.connect(self._refresh_worker.run)
        self._refresh_worker.status.connect(self._set_refresh_status)
        self._refresh_worker.finished.connect(self._on_refresh_finished)
        self._refresh_worker.error.connect(self._on_refresh_error)
        self._refresh_worker.finished.connect(self._refresh_thread.quit)
        self._refresh_worker.error.connect(self._refresh_thread.quit)
        self._refresh_thread.finished.connect(self._refresh_worker.deleteLater)
        self._refresh_thread.finished.connect(lambda: setattr(self, "_refresh_thread", None))
        self._refresh_thread.finished.connect(lambda: setattr(self, "_refresh_worker", None))
        self._refresh_thread.finished.connect(self._refresh_thread.deleteLater)

        self._refresh_thread.start()

    def _set_refresh_status(self, message: str):
        self.refresh_status_label.setText(message)
        self.statusBar().showMessage(message)

    def _on_refresh_finished(self):
        self.refresh_table()
        self._set_refresh_status("更新完成")
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("更新價格")

    def _on_refresh_error(self, error_msg: str):
        self._set_refresh_status("更新失敗")
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("更新價格")
        QMessageBox.warning(self, "錯誤", f"更新價格時發生錯誤: {error_msg}")
    
    def _create_asset_section(self, asset_type: AssetType) -> QWidget:
        """為特定資產類型創建標籤頁內容（一頁式緊湊設計）"""
        # 創建容器 Widget
        container = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)
        container.setLayout(layout)
        
        # 標題和統計資訊（標籤頁內顯示）
        header_layout = QHBoxLayout()
        
        # 排序按鈕
        sort_btn = QPushButton("排序")
        sort_btn.setMaximumWidth(72)
        sort_btn.setMaximumHeight(32)
        sort_btn.clicked.connect(lambda: self._show_sort_dialog(asset_type))
        header_layout.addWidget(sort_btn)
        
        header_layout.addStretch()
        
        stats_label = QLabel()
        stats_label.setFont(QFont("Arial", 9))
        stats_label.setStyleSheet("color: #526274; padding: 4px;")
        self._update_type_stats(stats_label, asset_type)
        header_layout.addWidget(stats_label)
        layout.addLayout(header_layout)
        
        # 使用樹狀表格（支援展開查看相同資產的多筆買入記錄）
        table = AssetTreeWidget(asset_type, self._on_manual_order_changed)
        table.setColumnCount(7)
        table.setHeaderLabels([
            "代號", "名稱", "數量", "成本", 
            "價格", "市值", "損益(含已實現)"
        ])
        # 允許調整欄位大小
        table.header().setSectionResizeMode(QHeaderView.Interactive)
        table.header().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTreeWidget.SelectRows)
        table.setEditTriggers(QTreeWidget.NoEditTriggers)
        table.setRootIsDecorated(True)
        table.setExpandsOnDoubleClick(False)
        table.setItemsExpandable(True)
        table.setSortingEnabled(False)  # 避免拖拉後被自動排序打亂
        
        table.setColumnWidth(0, 110)
        table.setColumnWidth(1, 220)
        table.setColumnWidth(2, 130)
        table.setColumnWidth(3, 135)
        table.setColumnWidth(4, 140)
        table.setColumnWidth(5, 155)
        table.setColumnWidth(6, 190)
        
        table.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #d8e0ea;
                border-radius: 6px;
                background-color: white;
                alternate-background-color: #f8fafc;
                font-size: 10.5pt;
            }
            QTreeWidget::item {
                padding: 5px 6px;
            }
            QTreeWidget::item:selected {
                background: #dcecff;
                color: #14213d;
            }
            QHeaderView::section {
                background-color: #eef3f8;
                color: #324457;
                padding: 7px;
                font-size: 10pt;
                font-weight: bold;
                border: none;
                border-right: 1px solid #d8e0ea;
                border-bottom: 1px solid #cbd5df;
            }
        """)
        
        layout.addWidget(table, 1)  # 使用 stretch factor 讓表格填滿剩餘空間
        
        # 儲存 table 和 stats_label 的引用
        container.table = table
        container.stats_label = stats_label
        container.asset_type = asset_type
        
        return container
    
    def _update_type_stats(self, label: QLabel, asset_type: AssetType):
        """更新特定資產類型的統計資訊"""
        stats = self.portfolio_manager.get_type_statistics(asset_type)
        assets = [a for a in self.portfolio_manager.get_all_assets() if a.asset_type == asset_type]
        
        # 根據資產類型選擇貨幣符號；已實現+未實現分開顯示
        if asset_type == AssetType.METAL:
            currency_symbol = "NT$"
            usd_to_twd = self.portfolio_manager.currency_converter.get_usd_to_twd_rate(force_update=True)
            total_value = self.portfolio_manager.currency_converter.convert_to_twd(stats['total_value'], "USD")
            total_cost = self.portfolio_manager.currency_converter.convert_to_twd(stats['total_cost'], "TWD")
            total_unreal = total_value - total_cost
            total_realized = sum(a.realized_pnl for a in assets)
            total_pnl = total_realized + total_unreal
            denom = sum(a.total_buy_cash for a in assets)
            # METAL 規則沿用：百分比只看未實現
            total_pnl_percent = (total_unreal / denom * 100) if denom > 0 else 0.0
        elif asset_type == AssetType.CRYPTO:
            currency_symbol = "$"
            total_value = stats['total_value']
            total_cost = stats['total_cost']
            total_unreal = stats['total_unrealized_pnl']
            total_realized = stats['total_realized_pnl']
            total_pnl = stats['total_pnl']
            denom = sum(a.total_buy_cash for a in assets)
            # Crypto（例如 TAO）：括號百分比用總損益/累計買入成本
            total_pnl_percent = (total_pnl / denom * 100) if denom > 0 else 0.0
        elif asset_type == AssetType.US_STOCK:
            currency_symbol = "$"
            total_value = stats['total_value']
            total_cost = stats['total_cost']
            total_unreal = stats['total_unrealized_pnl']
            total_realized = stats['total_realized_pnl']
            total_pnl = stats['total_pnl']
            denom = sum(a.total_buy_cash for a in assets)
            # 台幣/美股/基金：百分比用合計（已實現+未實現）
            total_pnl_percent = (total_pnl / denom * 100) if denom > 0 else 0.0
        elif asset_type == AssetType.HK_STOCK:
            currency_symbol = "HK$"
            total_value = stats['total_value']
            total_cost = stats['total_cost']
            total_unreal = stats['total_unrealized_pnl']
            total_realized = stats['total_realized_pnl']
            total_pnl = stats['total_pnl']
            denom = sum(a.total_buy_cash for a in assets)
            total_pnl_percent = (total_pnl / denom * 100) if denom > 0 else 0.0
        else:
            currency_symbol = "NT$"
            total_value = stats['total_value']
            total_cost = stats['total_cost']
            total_unreal = stats['total_unrealized_pnl']
            total_realized = stats['total_realized_pnl']
            total_pnl = stats['total_pnl']
            denom = sum(a.total_buy_cash for a in assets)
            # 台股/基金：百分比用合計（已實現+未實現）
            total_pnl_percent = (total_pnl / denom * 100) if denom > 0 else 0.0
        
        stats_text = (
            f"項目: {stats['count']} | "
            f"市值: {currency_symbol} {total_value:,.2f} | "
            f"持倉成本: {currency_symbol} {total_cost:,.2f} | "
            f"已實現: {currency_symbol} {total_realized:,.2f} | "
            f"未實現: {currency_symbol} {total_unreal:,.2f} | "
            f"合計: {currency_symbol} {total_pnl:,.2f} ({total_pnl_percent:+.2f}%)"
        )
        label.setText(stats_text)
        
        if total_pnl > 0:
            label.setStyleSheet("color: darkgreen; font-weight: bold;")
        elif total_pnl < 0:
            label.setStyleSheet("color: darkred; font-weight: bold;")
        else:
            label.setStyleSheet("color: #666;")
    
    def _show_sort_dialog(self, asset_type: AssetType):
        """顯示排序對話框"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"排序設定 - {asset_type.value}")
        dialog.setMinimumWidth(300)
        layout = QVBoxLayout()
        
        # 排序欄位選擇
        layout.addWidget(QLabel("排序依據:"))
        sort_key_combo = QComboBox()
        sort_key_combo.addItems(["代號", "名稱", "數量", "成本", "價格", "市值", "損益(含已實現)"])
        layout.addWidget(sort_key_combo)
        
        # 排序順序
        layout.addWidget(QLabel("排序順序:"))
        sort_order_combo = QComboBox()
        sort_order_combo.addItems(["升序", "降序"])
        layout.addWidget(sort_order_combo)
        
        # 載入當前設定
        if asset_type in self.sort_settings:
            current_key = self.sort_settings[asset_type]['key']
            current_order = self.sort_settings[asset_type]['order']
            key_map = {'symbol': 0, 'name': 1, 'quantity': 2, 'cost': 3, 'price': 4, 'value': 5, 'pnl': 6}
            order_map = {'asc': 0, 'desc': 1}
            if current_key in key_map:
                sort_key_combo.setCurrentIndex(key_map[current_key])
            if current_order in order_map:
                sort_order_combo.setCurrentIndex(order_map[current_order])
        
        # 按鈕
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("確定")
        cancel_btn = QPushButton("取消")
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.setLayout(layout)
        
        if dialog.exec() == QDialog.Accepted:
            key_map = {0: 'symbol', 1: 'name', 2: 'quantity', 3: 'cost', 4: 'price', 5: 'value', 6: 'pnl'}
            order_map = {0: 'asc', 1: 'desc'}
            
            self.sort_settings[asset_type] = {
                'key': key_map[sort_key_combo.currentIndex()],
                'order': order_map[sort_order_combo.currentIndex()]
            }
            # 重新整理表格以應用排序
            self.refresh_table()
    
    def _asset_display_total_pnl(self, asset) -> float:
        """列上損益：已實現 + 未實現（貴金屬未實現改以台幣計）。"""
        if asset.asset_type == AssetType.METAL:
            asset_currency = self.portfolio_manager._get_asset_currency(asset)
            usd_to_twd_rate = self.portfolio_manager.currency_converter.get_usd_to_twd_rate(force_update=True)
            current_value_twd = asset.current_value * usd_to_twd_rate
            total_cost_twd = self.portfolio_manager.currency_converter.convert_to_twd(
                asset.total_cost, asset_currency
            )
            unreal_twd = current_value_twd - total_cost_twd
            return float(asset.realized_pnl) + unreal_twd
        return float(asset.total_pnl)

    def _currency_symbol(self, currency: str) -> str:
        if currency == "TWD":
            return "NT$"
        if currency == "HKD":
            return "HK$"
        return "$"

    def _asset_display_pnl_percent(self, asset) -> float:
        """
        主表格（清單中的大項）百分比：
        規則：
        - 台股/美股/基金：括號百分比用（已實現+未實現）/累計買入成本
        - Crypto（例如 TAO）：括號百分比用（已實現+未實現）/累計買入成本
        """
        denom = float(getattr(asset, "total_buy_cash", 0.0) or 0.0)
        if denom <= 0:
            return 0.0

        if asset.asset_type == AssetType.METAL:
            asset_currency = self.portfolio_manager._get_asset_currency(asset)
            denom_twd = self.portfolio_manager.currency_converter.convert_to_twd(denom, asset_currency)
            if denom_twd <= 0:
                return 0.0
            # METAL：unrealized 需要用台幣計價
            current_value_twd = asset.current_value * self.portfolio_manager.currency_converter.get_usd_to_twd_rate(force_update=True)
            total_cost_twd = self.portfolio_manager.currency_converter.convert_to_twd(asset.total_cost, asset_currency)
            unreal_twd = current_value_twd - total_cost_twd
            return (float(unreal_twd) / float(denom_twd)) * 100.0

        if asset.asset_type == AssetType.CRYPTO:
            # Crypto（例如 TAO）：括號百分比以「已實現 + 未實現（總損益）」/累計買入成本
            total = float(asset.realized_pnl + asset.unrealized_pnl)
            return (total / denom) * 100.0

        total = float(asset.realized_pnl + asset.unrealized_pnl)
        return (total / denom) * 100.0

    def _apply_sort(self, asset_type: AssetType, assets: list) -> list:
        """應用排序設定"""
        if asset_type not in self.sort_settings:
            # 若有手拉排序，優先採用；其餘再按代號補齊
            order = self.manual_order.get(asset_type) or []
            if order:
                idx_map = {sym: i for i, sym in enumerate(order)}
                return sorted(assets, key=lambda a: (idx_map.get(a.symbol, 10**9), a.symbol))
            return sorted(assets, key=lambda x: x.symbol)
        
        sort_key = self.sort_settings[asset_type]['key']
        sort_order = self.sort_settings[asset_type]['order']
        
        # 定義排序鍵的映射
        def get_sort_value(asset):
            if sort_key == 'symbol':
                return asset.symbol
            elif sort_key == 'name':
                return asset.name
            elif sort_key == 'quantity':
                return asset.quantity
            elif sort_key == 'cost':
                return asset.avg_cost
            elif sort_key == 'price':
                return asset.current_price
            elif sort_key == 'value':
                return asset.current_value
            elif sort_key == 'pnl':
                return self._asset_display_total_pnl(asset)
            return asset.symbol
        
        sorted_assets = sorted(assets, key=get_sort_value, reverse=(sort_order == 'desc'))
        return sorted_assets
    
    def refresh_table(self):
        """更新表格顯示"""
        # 重新建持倉（含已了結 lot），確保像 7822 這類數量變 0 的標的仍能展開查看買賣明細
        self.portfolio_manager.rebuild_holdings_preserve_prices()

        assets_by_type = self.portfolio_manager.get_assets_by_type()
        
        # 更新每個資產類型區域
        for asset_type, section in self.asset_sections.items():
            table = section.table
            table.clear()  # 清空樹狀表格
            
            assets = assets_by_type.get(asset_type, [])
            if self.hide_zero_quantity_checkbox.isChecked():
                assets = [asset for asset in assets if abs(asset.quantity) > 1e-12]
            
            # 應用排序
            assets = self._apply_sort(asset_type, assets)
            
            for asset in assets:
                # 主項目（資產總覽）
                unit = asset.get_unit_display()
                
                # 如果是金屬且單位不是盎司，需要轉換顯示數量
                display_quantity = asset.quantity
                display_avg_cost = asset.avg_cost
                display_current_price = asset.current_price
                display_current_value = asset.current_value
                
                if asset.asset_type == AssetType.METAL and asset.unit != "盎司":
                    # 將盎司轉換為用戶選擇的單位
                    from utils.gold_converter import convert_between_units, GOLD_UNIT_CONVERSIONS
                    display_quantity = convert_between_units(asset.quantity, "盎司", asset.unit)
                    # 成本價也需要轉換（從每盎司轉換為每單位）
                    unit_grams = GOLD_UNIT_CONVERSIONS.get(asset.unit, 1.0)
                    display_avg_cost = asset.avg_cost * (unit_grams / 31.1035)
                    
                    # 當前價格也需要轉換：從美元/盎司轉換為台幣/單位
                    # 1. 先將美元/盎司轉換為台幣/盎司
                    usd_to_twd_rate = self.portfolio_manager.currency_converter.get_usd_to_twd_rate()
                    price_twd_per_ounce = asset.current_price * usd_to_twd_rate
                    # 2. 再從台幣/盎司轉換為台幣/單位
                    display_current_price = price_twd_per_ounce * (unit_grams / 31.1035)
                    # 3. 市值也需要轉換（從美元轉換為台幣）
                    display_current_value = asset.current_value * usd_to_twd_rate
                
                # 創建主項目（資產總覽）
                main_item = QTreeWidgetItem(table)
                main_item.setText(0, asset.symbol)
                asset_currency = self.portfolio_manager._get_asset_currency(asset)
                display_symbol = self._currency_symbol(asset_currency)
                # 名稱可能太長，截斷顯示
                name_display = asset.name[:15] + "..." if len(asset.name) > 15 else asset.name
                main_item.setText(1, name_display)
                # 根據單位調整數量顯示精度
                if unit == "股":
                    qty_text = f"{display_quantity:.0f} {unit}"
                else:
                    qty_text = f"{display_quantity:.2f} {unit}"
                main_item.setText(2, qty_text)
                
                # 成本顯示：金屬用台幣，其他保持原樣
                if asset.asset_type == AssetType.METAL:
                    main_item.setText(3, f"NT$ {display_avg_cost:.2f}")
                else:
                    main_item.setText(3, f"{display_symbol} {display_avg_cost:.2f}")
                
                # 價格顯示：金屬用台幣/單位，其他保持原樣
                if asset.asset_type == AssetType.METAL:
                    price_text = f"NT$ {display_current_price:.2f}/{unit}" if display_current_price > 0 else "N/A"
                else:
                    price_text = f"{display_symbol} {display_current_price:.2f}" if display_current_price > 0 else "N/A"
                main_item.setText(4, price_text)
                
                # 市值顯示：金屬用台幣，其他保持原樣
                if asset.asset_type == AssetType.METAL:
                    main_item.setText(5, f"NT$ {display_current_value:.2f}")
                else:
                    main_item.setText(5, f"{display_symbol} {display_current_value:.2f}")
                
                # 損益顯示：金屬用台幣，其他保持原樣
                if asset.asset_type == AssetType.METAL:
                    # 金屬的損益計算需要考慮貨幣轉換
                    # current_value 是美元，total_cost 是台幣（如果用戶用台幣購買）
                    # 需要統一貨幣後計算損益
                    asset_currency = self.portfolio_manager._get_asset_currency(asset)
                    usd_to_twd_rate = self.portfolio_manager.currency_converter.get_usd_to_twd_rate(force_update=True)
                    
                    # 將當前市值轉換為台幣
                    current_value_twd = asset.current_value * usd_to_twd_rate
                    # 總成本已經是台幣（如果用戶用台幣購買）
                    total_cost_twd = self.portfolio_manager.currency_converter.convert_to_twd(asset.total_cost, asset_currency)
                    
                    # 台幣：已實現 + 未實現
                    unreal_twd = current_value_twd - total_cost_twd
                    pnl = float(asset.realized_pnl) + unreal_twd
                    pnl_percent = self._asset_display_pnl_percent(asset)
                    pnl_text = f"NT$ {pnl:.2f} ({pnl_percent:+.2f}%)"
                else:
                    pnl = self._asset_display_total_pnl(asset)
                    pnl_percent = self._asset_display_pnl_percent(asset)
                    cur = self.portfolio_manager._get_asset_currency(asset)
                    sym = self._currency_symbol(cur)
                    pnl_text = f"{sym} {pnl:.2f} ({pnl_percent:+.2f}%)"
                main_item.setText(6, pnl_text)
                
                # 設定顏色
                if pnl > 0:
                    main_item.setForeground(6, Qt.darkGreen)
                elif pnl < 0:
                    main_item.setForeground(6, Qt.darkRed)
                
                # 儲存資產資訊到項目中，以便刪除時使用
                main_item.setData(0, Qt.UserRole, asset)
                
                # 子項目：
                # - 金屬：用持倉 lot（positions）
                # - 其他：用交易清單（BUY/SELL），確保像 7822 這種「買入 1 筆 + 賣出多筆」也能展開看到多行
                if asset.asset_type == AssetType.METAL and len(asset.positions) > 0:
                    for position in asset.positions:
                        child_item = QTreeWidgetItem(main_item)
                        child_item.setText(0, "")  # 代號留空
                        child_item.setText(1, f"買入日期: {position.buy_date.strftime('%Y-%m-%d')}")
                        
                        # 轉換顯示數量（如果是金屬）
                        pos_display_quantity = position.quantity
                        pos_display_cost = position.cost_price
                        pos_display_price = position.current_price
                        pos_display_value = position.current_value
                        
                        if asset.asset_type == AssetType.METAL and asset.unit != "盎司":
                            from utils.gold_converter import convert_between_units, GOLD_UNIT_CONVERSIONS
                            pos_display_quantity = convert_between_units(position.quantity, "盎司", asset.unit)
                            unit_grams = GOLD_UNIT_CONVERSIONS.get(asset.unit, 1.0)
                            pos_display_cost = position.cost_price * (unit_grams / 31.1035)
                            
                            # 當前價格也需要轉換：從美元/盎司轉換為台幣/單位
                            usd_to_twd_rate = self.portfolio_manager.currency_converter.get_usd_to_twd_rate()
                            price_twd_per_ounce = position.current_price * usd_to_twd_rate
                            pos_display_price = price_twd_per_ounce * (unit_grams / 31.1035)
                            # 市值也需要轉換（從美元轉換為台幣）
                            pos_display_value = position.current_value * usd_to_twd_rate
                        
                        if unit == "股":
                            pos_qty_text = f"{pos_display_quantity:.0f} {unit}"
                        else:
                            pos_qty_text = f"{pos_display_quantity:.2f} {unit}"
                        child_item.setText(2, pos_qty_text)
                        
                        # 成本顯示：金屬用台幣，其他保持原樣
                        if asset.asset_type == AssetType.METAL:
                            child_item.setText(3, f"NT$ {pos_display_cost:.2f}")
                        else:
                            child_item.setText(3, f"{display_symbol} {pos_display_cost:.2f}")
                        
                        # 價格顯示：金屬用台幣/單位，其他保持原樣
                        if asset.asset_type == AssetType.METAL:
                            pos_price_text = f"NT$ {pos_display_price:.2f}/{unit}" if pos_display_price > 0 else "N/A"
                        else:
                            pos_price_text = f"{display_symbol} {pos_display_price:.2f}" if pos_display_price > 0 else "N/A"
                        child_item.setText(4, pos_price_text)
                        
                        # 市值顯示：金屬用台幣，其他保持原樣
                        if asset.asset_type == AssetType.METAL:
                            child_item.setText(5, f"NT$ {pos_display_value:.2f}")
                        else:
                            child_item.setText(5, f"{display_symbol} {pos_display_value:.2f}")
                        
                        # 損益顯示：金屬用台幣，其他保持原樣
                        if asset.asset_type == AssetType.METAL:
                            # 金屬的損益計算需要考慮貨幣轉換
                            asset_currency = self.portfolio_manager._get_asset_currency(asset)
                            usd_to_twd_rate = self.portfolio_manager.currency_converter.get_usd_to_twd_rate(force_update=True)
                            
                            # 將當前市值轉換為台幣
                            pos_current_value_twd = position.current_value * usd_to_twd_rate
                            # 總成本已經是台幣（如果用戶用台幣購買）
                            pos_total_cost_twd = self.portfolio_manager.currency_converter.convert_to_twd(position.total_cost, asset_currency)
                            
                            # 計算台幣損益
                            pos_pnl_twd = pos_current_value_twd - pos_total_cost_twd
                            pos_pnl_percent = (pos_pnl_twd / pos_total_cost_twd * 100) if pos_total_cost_twd > 0 else 0.0
                            pos_pnl_text = f"NT$ {pos_pnl_twd:.2f} ({pos_pnl_percent:+.2f}%)"
                            pos_pnl = pos_pnl_twd
                        else:
                            pos_pnl = position.unrealized_pnl
                            pos_pnl_percent = position.unrealized_pnl_percent
                            pos_pnl_text = f"{display_symbol} {pos_pnl:.2f} ({pos_pnl_percent:+.2f}%)"
                        child_item.setText(6, pos_pnl_text)
                        
                        # 設定顏色
                        if pos_pnl > 0:
                            child_item.setForeground(6, Qt.darkGreen)
                        elif pos_pnl < 0:
                            child_item.setForeground(6, Qt.darkRed)
                    
                if asset.asset_type != AssetType.METAL:
                    txs = [
                        t for t in self.portfolio_manager.transactions
                        if t.symbol == asset.symbol and t.asset_type == asset.asset_type
                    ]
                    if txs:
                        cur = self.portfolio_manager._get_asset_currency(asset)
                        sym = self._currency_symbol(cur)
                        def _tx_display_sort_key(t):
                            # 最新日期在上方；同一天固定 BUY 在 SELL 上方
                            dt = self.portfolio_manager._normalize_tx_date(t.date)
                            ts = dt.timestamp()
                            type_order = 0 if t.transaction_type == TransactionType.BUY else 1
                            return (-ts, type_order, str(t.id))

                        txs_sorted = sorted(txs, key=_tx_display_sort_key)
                        
                        for t in txs_sorted:
                            child_item = QTreeWidgetItem(main_item)
                            child_item.setText(0, "")  # 代號留空
                            child_item.setText(1, f"{t.transaction_type.value}日期: {t.date.strftime('%Y-%m-%d')}")
                            
                            # 數量：展開清單要顯示原始每筆交易數量
                            if unit == "股":
                                qty_text = f"{t.quantity:.0f} {unit}"
                            else:
                                qty_text = f"{t.quantity:.2f} {unit}"
                            child_item.setText(2, qty_text)
                            
                            fee = t.fee or 0.0
                            eff_price = t.price
                            if t.quantity and t.quantity > 0:
                                if t.transaction_type == TransactionType.BUY:
                                    eff_price = t.price + (fee / t.quantity)
                                elif t.transaction_type == TransactionType.SELL:
                                    eff_price = t.price - (fee / t.quantity)
                            
                            # 成交（含/扣手續費）均價/單價
                            child_item.setText(3, f"{sym} {eff_price:.2f}")
                            
                            # 參考：顯示目前價格；市值（index=5）：
                            # - BUY：用「目前價格 * 原始買入數量」（符合你截圖）
                            # - SELL：已了結，顯示 '-'
                            if display_current_price and display_current_price > 0:
                                child_item.setText(4, f"{sym} {display_current_price:.2f}")
                                if t.transaction_type == TransactionType.BUY:
                                    child_item.setText(5, f"{sym} {t.quantity * display_current_price:,.2f}")
                                else:
                                    child_item.setText(5, "-")
                            else:
                                child_item.setText(4, "N/A")
                                child_item.setText(5, "-")
                            
                            # 損益規則（符合你描述）：
                            # - BUY：用「目前市值（目前價格*買入數量）」-「買入成本基礎（含手續費）」
                            # - SELL：用 FIFO 計算出的已實現損益
                            if t.transaction_type == TransactionType.BUY:
                                if display_current_price and display_current_price > 0 and t.quantity > 0:
                                    buy_cost_basis = t.quantity * eff_price  # eff_price 含手續費（BUY）
                                    pnl = t.quantity * display_current_price - buy_cost_basis
                                    pnl_percent = (pnl / buy_cost_basis * 100) if buy_cost_basis > 0 else 0.0
                                else:
                                    pnl = 0.0
                                    pnl_percent = 0.0
                                pnl_text = f"{sym} {pnl:.2f} ({pnl_percent:+.2f}%)"

                                if pnl > 0:
                                    child_item.setForeground(6, Qt.darkGreen)
                                elif pnl < 0:
                                    child_item.setForeground(6, Qt.darkRed)
                            else:
                                pnl = float(self.portfolio_manager.realized_pnl_by_transaction_id.get(t.id, 0.0))
                                cost_basis = float(self.portfolio_manager.realized_cost_basis_by_transaction_id.get(t.id, 0.0))
                                pnl_percent = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0
                                pnl_text = f"{sym} {pnl:.2f} ({pnl_percent:+.2f}%)"

                                if pnl > 0:
                                    child_item.setForeground(6, Qt.darkGreen)
                                elif pnl < 0:
                                    child_item.setForeground(6, Qt.darkRed)

                            child_item.setText(6, pnl_text)

            # 更新統計資訊
            self._update_type_stats(section.stats_label, asset_type)
            
            # 添加右鍵選單功能（刪除交易）
            table.setContextMenuPolicy(Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(lambda pos, t=table, at=asset_type: self._show_context_menu(pos, t, at))
            
            # 儲存表格引用以便後續使用
            section.table = table
        
        # 更新總覽（統一以台幣計價，所有幣種自動換算）
        # 獲取選中的資產類型
        included_types = [
            asset_type for asset_type, checkbox in self.asset_type_checkboxes.items()
            if checkbox.isChecked()
        ]
        # 注意：included_types=None 代表「全部都算」；空清單代表「都不算」
        total_value_twd = self.portfolio_manager.get_total_value("TWD", included_types)
        total_cost_twd = self.portfolio_manager.get_total_cost("TWD", included_types)
        total_unreal_twd = self.portfolio_manager.get_total_unrealized_pnl("TWD", included_types)
        total_realized_twd = self.portfolio_manager.get_total_realized_pnl("TWD", included_types)
        total_combined_twd = total_unreal_twd + total_realized_twd
        unreal_pct = (total_unreal_twd / total_cost_twd * 100) if total_cost_twd > 0 else 0.0
        
        self.total_value_label.setText(f"NT$ {total_value_twd:,.2f}")
        self.total_cost_label.setText(f"NT$ {total_cost_twd:,.2f}")
        self.total_pnl_label.setText(f"NT$ {total_unreal_twd:,.2f} ({unreal_pct:+.2f}%)")
        self.total_realized_label.setText(f"NT$ {total_realized_twd:,.2f}")
        self.total_combined_pnl_label.setText(f"NT$ {total_combined_twd:,.2f}")
        self._refresh_history_chart()

        gain_color = "#0f7b59" if total_combined_twd > 0 else "#b42318" if total_combined_twd < 0 else "#14213d"
        unreal_color = "#0f7b59" if total_unreal_twd > 0 else "#b42318" if total_unreal_twd < 0 else "#14213d"
        realized_color = "#0f7b59" if total_realized_twd > 0 else "#b42318" if total_realized_twd < 0 else "#14213d"
        self.total_pnl_label.setStyleSheet(f"color: {unreal_color};")
        self.total_realized_label.setStyleSheet(f"color: {realized_color};")
        self.total_combined_pnl_label.setStyleSheet(f"color: {gain_color};")
        self.total_card.setStyleSheet(f"""
            QFrame#summaryPanel {{
                background: #ffffff;
                border: 1px solid {gain_color if total_combined_twd else "#d8e0ea"};
                border-radius: 8px;
            }}
        """)

    def _refresh_history_chart(self):
        if not hasattr(self, "history_chart"):
            return
        snapshots = self.portfolio_manager.get_daily_asset_snapshots()
        included_types = [
            asset_type for asset_type, checkbox in self.asset_type_checkboxes.items()
            if checkbox.isChecked()
        ]
        self.history_chart.set_visible_asset_types(included_types)
        self.history_chart.set_data(snapshots, self._history_scale)
    
    def _on_asset_type_checkbox_changed(self):
        """當資產類型 checkbox 狀態改變時，重新計算總資產"""
        self._save_included_types_setting()
        self.refresh_table()

    def _on_hide_zero_quantity_changed(self):
        """切換是否隱藏數量為 0 的資產。"""
        self._save_hide_zero_setting()
        self.refresh_table()
    
    def _show_context_menu(self, position: QPoint, table: QTreeWidget, asset_type: AssetType):
        """顯示右鍵選單（編輯/刪除交易）"""
        item = table.itemAt(position)
        if item is None:
            return
        
        # 如果是子項目，獲取父項目
        if item.parent() is not None:
            item = item.parent()
        
        # 獲取該行的資產
        asset = item.data(0, Qt.UserRole)
        if asset is None:
            return
        
        # 創建選單
        menu = QMenu(self)
        
        # 查找該資產的所有交易記錄
        transactions = [t for t in self.portfolio_manager.transactions 
                       if t.symbol == asset.symbol and t.asset_type == asset.asset_type]
        
        if not transactions:
            return
        
        # 為每筆交易創建選單項
        for transaction in transactions:
            edit_text = f"編輯: {transaction.transaction_type.value} {transaction.quantity} {asset.get_unit_display()} @ {transaction.date.strftime('%Y-%m-%d')}"
            edit_action = QAction(edit_text, self)
            edit_action.setData(transaction.id)
            edit_action.triggered.connect(lambda checked, tx=transaction: self._edit_transaction(tx))
            menu.addAction(edit_action)

            delete_text = f"刪除: {transaction.transaction_type.value} {transaction.quantity} {asset.get_unit_display()} @ {transaction.date.strftime('%Y-%m-%d')}"
            delete_action = QAction(delete_text, self)
            delete_action.setData(transaction.id)  # 儲存交易ID
            delete_action.triggered.connect(lambda checked, tid=transaction.id: self._delete_transaction(tid))
            menu.addAction(delete_action)
        
        # 顯示選單
        menu.exec_(table.mapToGlobal(position))
    
    def _delete_transaction(self, transaction_id: str):
        """刪除交易記錄"""
        reply = QMessageBox.question(
            self, 
            "確認刪除", 
            "確定要刪除這筆交易記錄嗎？\n刪除後將重新計算資產。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.portfolio_manager.delete_transaction(transaction_id)
                self.refresh_prices()  # 重新更新價格
                self.refresh_table()  # 重新整理表格
                QMessageBox.information(self, "成功", "交易記錄已刪除")
            except Exception as e:
                QMessageBox.warning(self, "錯誤", f"刪除交易時發生錯誤: {str(e)}")

    def _edit_transaction(self, transaction: Transaction):
        """編輯既有交易記錄（避免 key 錯時可更正）。"""
        dialog = TransactionDialog(self, transaction=transaction)
        updated = dialog.get_transaction()
        if updated is None:
            return
        if not updated.symbol or not updated.name:
            QMessageBox.warning(self, "錯誤", "請輸入代號和名稱")
            return

        try:
            self.portfolio_manager.update_transaction(updated)
            self.refresh_prices()
            self.refresh_table()
            QMessageBox.information(self, "成功", "交易已更新")
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"更新交易時發生錯誤: {str(e)}")


def main():
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
