# Personal Portfolio Dashboard

一個整合多種資產的個人投資組合儀表板（PySide6 桌面程式），類似券商庫存頁面，可整合台股、美股、港股、基金、加密貨幣、貴金屬等。

## 功能特色

### Phase 1（已實現）

- 支援多種資產類型：台股、美股、港股、基金、加密貨幣、貴金屬
- 手動輸入／編輯／刪除交易記錄（右鍵選單）
- 自動計算現值、未實現損益、已實現損益（FIFO）與合計損益
- 全資產總覽（卡片式設計），可依類型勾選是否列入總資產
- 資產列表預設依「市值 / 降序」排序，並可勾選隱藏數量為 0 的資產
- 即時／定期更新價格（介面上「更新價格」，並有背景執行緒避免卡住 UI；另有每 5 分鐘自動更新）
- SQLite 儲存（`portfolio.db`），下次開啟自動載入
- 依資產類型分頁（Tab），各頁獨立統計與排序／手動拖曳排序
- 同一標的多筆買賣可展開檢視明細
- 資產趨勢圖：保存每日總資產、台股收盤市值、美股收盤市值

### Phase 2（規劃中）

- 現金帳戶
- 其他報表與匯出強化

### Phase 3（規劃中）

- 月報表、資產配置分析
- 匯出 Excel / PDF

## 技術架構

- **Python**：建議 **3.10+**（需與目前 PySide6 發行版相容；例如 3.11、3.12、3.13）
- **PySide6**：Qt 視窗介面（含 **Shiboken6**，供 `gui/main_window.py` 使用）
- **SQLite**：內建於 Python，資料層見 `database/db_manager.py`
- **適配器模式**（擴充資料來源）
  - `StockPriceAdapter`（`adapters/stock_adapter.py`）：台／美／港股、基金 — **yfinance**
  - `CryptoPriceAdapter`（`adapters/crypto_adapter.py`）：加密貨幣 — **ccxt**、**requests**
  - `GoldPriceAdapter`（`adapters/gold_adapter.py`）：貴金屬 — **yfinance**
  - `CurrencyConverter`（`utils/currency_converter.py`）：匯率 — **yfinance**

## 安裝

建立虛擬環境後安裝依賴（若使用 conda，可先 `conda activate <你的環境>`）：

```bash
pip install -r requirements.txt
```

### 相依套件對照（`requirements.txt`）

| 套件 | 用途 |
|------|------|
| PySide6 | 視窗 GUI |
| yfinance | 報價、名稱查詢、匯率輔助 |
| ccxt | 加密貨幣報價 |
| requests | HTTP（與 Crypto 流程等） |
| urllib3 | HTTP 底層（程式中有直接使用） |
| pyinstaller | 將程式打包成 Windows `.exe`（見下方「打包」一節） |

未列於檔案中、但會由上述套件自動安裝的相依（例如 **charset-normalizer**、**certifi** 等）無須手動填寫。

## 使用方式

1. 啟動程式：

```bash
python main.py
```

2. **新增交易**：按「新增交易」或快捷鍵 **F1**，填寫資產類型、代號、數量、價格等；系統會計算平均成本與持倉。
3. **更新價格**：按「更新價格」或 **F5**；首次載入約 1 秒後也會自動觸發一次背景更新。
4. **編輯／刪除**：在表格列上 **右鍵**，選擇對應交易。
5. **資產趨勢**：切到「資產趨勢」頁籤檢視折線圖，可切換每日／星期／月／3月／半年／年。每日資料會在「更新價格」完成後寫入；若 app 沒有每天開啟，下一次更新價格會補齊缺漏日期。

### 每日資產快照

`portfolio.db` 會自動建立 `daily_asset_snapshots` 表：

| 欄位 | 說明 |
|------|------|
| `snapshot_date` | 日期 |
| `total_value_twd` | 當日總資產（台幣） |
| `tw_stock_value_twd` | 台股收盤市值（台幣） |
| `us_stock_value_twd` | 美股收盤市值（台幣） |

補資料規則：更新價格後，系統會從第一筆交易日期到今天檢查缺漏日期；台股、美股、港股、基金、貴金屬會用 Yahoo Finance 日收盤價回補，無法可靠回補的資產會盡量使用可取得的歷史或目前價格估算。

## 開發備註

### OneDrive 專案推送到 GitHub

這個專案放在 OneDrive 同步資料夾內，Git 可直接在目前資料夾操作，不需要每次另外找 temporary 資料夾。若之後重新整理或換電腦，流程如下：

```bash
cd C:\Users\chunw\OneDrive\github\golden_UI
conda activate golden

# 第一次才需要
git init
git branch -M main
git remote add origin https://github.com/kaede10263/ledger.git

# 日常更新
git status
git add .
git commit -m "Update portfolio dashboard"
git push -u origin main
```

注意：

- `.gitignore` 已排除 `build/`、`dist/`、`__pycache__/`、`*.db`，避免把本機打包產物與個人投資資料推上 GitHub。
- 如果 OneDrive 正在同步大量檔案，建議等同步完成再 commit / push，減少檔案鎖定或狀態跳動。

### 報價 API 評估

目前股票與基金報價使用 `yfinance`，美股常見會有延遲或資料更新不穩。若要改善美股即時性，可以考慮新增一個付費或需 API key 的 adapter：

| API | 適合情境 | 備註 |
|-----|----------|------|
| Alpaca Market Data | 想要 Python 友善、同時支援 REST / WebSocket | 免費通常是 IEX 即時資料；完整市場 SIP 需訂閱。 |
| Polygon.io | 需要完整美股市場資料、歷史資料與 WebSocket | 資料完整度高，但即時完整市場通常是付費方案。 |
| Twelve Data | 想用統一 API 管股票、ETF、外匯與加密貨幣 | 訂閱方案含即時／延遲資料，適合跨市場整合。 |
| Alpha Vantage | 較簡單的 REST quote / historical API | 免費層多有限制；美股即時或延遲 quote 通常需 premium。 |

建議下一步：先保留 `yfinance` 當 fallback，再新增 `AlpacaStockPriceAdapter` 或 `PolygonStockPriceAdapter`，用環境變數存 API key，例如 `ALPACA_API_KEY`、`ALPACA_API_SECRET` 或 `POLYGON_API_KEY`。

## 打包成 Windows `.exe`（PyInstaller）

`requirements.txt` 已包含 **pyinstaller**，安裝依賴後即可打包。

在專案根目錄（與 `main.py` 同層）執行：

```bash
# 若使用 conda 環境（例如專案慣用的 golden）
conda activate golden

python -m PyInstaller --onefile --windowed --name golden_ui main.py
```

與 `pyinstaller` 指令列工具等價（建議使用 `python -m PyInstaller`，可避免 PATH 指到別套 Python）：

```bash
pyinstaller --onefile --windowed --name golden_ui main.py
```

說明：

| 選項 | 作用 |
|------|------|
| `--onefile` | 打成單一 `.exe`（檔案較大，但好散佈） |
| `--windowed` | Windows 上不額外跳出主控台黑視窗（GUI 程式常用） |
| `--name golden_ui` | 產物檔名為 `golden_ui.exe`（未加則預設為 `main.exe`） |

產物位於 **`dist/golden_ui.exe`**。第一次打包後會產生 `golden_ui.spec`、`build/` 等；檔案體積大屬正常（內含 Qt 與 Python 執行環境）。之後若要重包，可先刪除 `build/`、`dist/` 再執行一次上述指令。

## 資產類型說明

### 台股

- 代號例如：`2330`（台積電）；系統會轉成 Yahoo Finance 格式（如 `2330.TW`）。

### 美股／基金（ETF）

- 代號例如：`AAPL`、`SPY`、`QQQ`。

### 港股

- 依適配器邏輯使用對應 Yahoo 代號格式（請依畫面／來源規則輸入）。

### 加密貨幣

- 代號例如：`BTC`、`ETH`；會轉為交易對（如 `BTC/USDT`）等形式向交易所取價。

### 貴金屬

- 以種類選擇（黃金／白銀等）；報價來自期貨／商品代號（如 Yahoo 商品代碼）。

## 專案結構

```
.
├── main.py                     # 程式入口
├── requirements.txt            # Python 相依套件
├── portfolio_manager.py       # 投資組合核心邏輯
├── portfolio.db               # SQLite（執行後自動建立／更新）
├── models/                    # 資料模型
│   ├── asset.py
│   ├── transaction.py
│   └── position.py
├── adapters/                  # 報價與資料適配器
│   ├── base_adapter.py
│   ├── stock_adapter.py
│   ├── crypto_adapter.py
│   └── gold_adapter.py
├── database/
│   └── db_manager.py          # SQLite 存取
├── utils/
│   ├── gold_converter.py      # 貴金屬單位換算
│   └── currency_converter.py  # 匯率／幣別轉換
├── gui/
│   └── main_window.py         # 主視窗 UI
└── test.py                    # 開發／測試用腳本（可選）
```

打包時可能多出 `build/`、`dist/`、`*.spec`，未列入上表。

## 擴展性

- 新增資產類型：新增 `AssetType`、對應 Adapter、並串到 `PortfolioManager`。
- 新增資料來源：實作繼承 `BasePriceAdapter` 的類別。
- 新功能：多在 `portfolio_manager.py` 與 `gui/main_window.py` 擴充。

## 注意事項

- 報價依賴網路與第三方 API；連線不穩時可能無法更新或延遲。
- 請定期備份 `portfolio.db`。
- 加密貨幣報價多為 USDT 計價；總覽可依設定換算為台幣等。

## License

MIT
