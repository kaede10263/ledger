import ccxt
import requests
import urllib3
from typing import Dict, Optional

from models.asset import AssetType
from .base_adapter import BasePriceAdapter


class CryptoPriceAdapter(BasePriceAdapter):
    """加密貨幣價格適配器"""

    CRYPTO_NAMES = {
        'BTC': 'Bitcoin',
        'ETH': 'Ethereum',
        'BNB': 'Binance Coin',
        'SOL': 'Solana',
        'ADA': 'Cardano',
        'XRP': 'Ripple',
        'DOT': 'Polkadot',
        'DOGE': 'Dogecoin',
        'MATIC': 'Polygon',
        'AVAX': 'Avalanche',
        'LINK': 'Chainlink',
        'UNI': 'Uniswap',
        'LTC': 'Litecoin',
        'ATOM': 'Cosmos',
        'ETC': 'Ethereum Classic',
        'AR': 'Arweave',
        'TAO': 'Bittensor',
        'ASTR': 'Astar',
        'APT': 'Aptos',
        'SUI': 'Sui',
        'OP': 'Optimism',
        'ARB': 'Arbitrum',
        'INJ': 'Injective',
        'SEI': 'Sei',
        'TIA': 'Celestia',
    }

    COINGECKO_SYMBOL_MAP = {
        'BTC': 'bitcoin',
        'ETH': 'ethereum',
        'BNB': 'binancecoin',
        'SOL': 'solana',
        'ADA': 'cardano',
        'XRP': 'ripple',
        'DOT': 'polkadot',
        'DOGE': 'dogecoin',
        'MATIC': 'matic-network',
        'AVAX': 'avalanche-2',
        'LINK': 'chainlink',
        'UNI': 'uniswap',
        'LTC': 'litecoin',
        'ATOM': 'cosmos',
        'ETC': 'ethereum-classic',
        'AR': 'arweave',
        'TAO': 'bittensor',
        'ASTR': 'astar',
        'APT': 'aptos',
        'SUI': 'sui',
        'OP': 'optimism',
        'ARB': 'arbitrum',
        'INJ': 'injective-protocol',
        'SEI': 'sei-network',
        'TIA': 'celestia',
    }

    EXCHANGE_NAMES = ['binance', 'coinbase', 'kraken', 'okx']

    def __init__(self):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.exchanges = []
        self.session = requests.Session()
        self._init_exchanges()

    def _init_exchanges(self):
        """初始化多個交易所"""
        for exchange_name in self.EXCHANGE_NAMES:
            try:
                exchange_class = getattr(ccxt, exchange_name)
                exchange = exchange_class({
                    'enableRateLimit': True,
                    'timeout': 10000,
                })
                self.exchanges.append(exchange)
            except Exception as e:
                print(f"Warning: Failed to initialize {exchange_name} exchange: {e}")

        if not self.exchanges:
            try:
                self.exchanges.append(
                    ccxt.binance({
                        'enableRateLimit': True,
                        'timeout': 10000
                    })
                )
            except Exception as e:
                print(f"Warning: Failed to initialize fallback Binance exchange: {e}")

    def _normalize_symbol(self, symbol: str) -> str:
        """正規化加密貨幣代號（例如 BTC -> BTC/USDT）"""
        symbol_upper = symbol.upper().strip()
        if '/' not in symbol_upper:
            return f"{symbol_upper}/USDT"
        return symbol_upper

    def _http_get_json(self, url: str, params: Optional[dict] = None, timeout: int = 10) -> Optional[dict]:
        """共用 HTTP GET JSON"""
        try:
            response = self.session.get(url, params=params, timeout=timeout, verify=False)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def get_crypto_name(self, symbol: str) -> Optional[str]:
        """獲取加密貨幣名稱"""
        try:
            return self.CRYPTO_NAMES.get(symbol.upper(), symbol.upper())
        except Exception as e:
            print(f"Error fetching crypto name for {symbol}: {e}")
            return None

    def _get_price_from_coingecko(self, symbol: str) -> Optional[float]:
        """從 CoinGecko API 獲取價格"""
        symbol_upper = symbol.upper().strip()
        coin_id = self.COINGECKO_SYMBOL_MAP.get(symbol_upper)

        if not coin_id:
            return None

        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": "usd"
        }

        data = self._http_get_json(url, params=params, timeout=10)
        if data and coin_id in data and "usd" in data[coin_id]:
            try:
                return float(data[coin_id]["usd"])
            except Exception:
                return None

        return None

    def _get_binance_pair_price(self, base_symbol: str, quote_symbol: str) -> Optional[float]:
        """從 Binance REST API 取得某交易對價格"""
        url = "https://api.binance.com/api/v3/ticker/price"
        params = {'symbol': f'{base_symbol.upper()}{quote_symbol.upper()}'}

        data = self._http_get_json(url, params=params, timeout=5)
        if data and 'price' in data:
            try:
                return float(data['price'])
            except Exception:
                return None
        return None

    def _get_price_from_binance_rest(self, symbol: str) -> Optional[float]:
        """從 Binance 公開 REST API 獲取價格"""
        symbol_upper = symbol.upper().strip()

        # 1. 先試 USDT 直對
        direct_price = self._get_binance_pair_price(symbol_upper, 'USDT')
        if direct_price is not None:
            return direct_price

        # 2. 再試其他交易對，再換算成 USDT
        for quote in ['BTC', 'ETH', 'BNB']:
            base_quote_price = self._get_binance_pair_price(symbol_upper, quote)
            quote_usdt_price = self._get_binance_pair_price(quote, 'USDT')

            if base_quote_price is not None and quote_usdt_price is not None:
                return base_quote_price * quote_usdt_price

        return None

    def _get_price_from_cryptocompare(self, symbol: str) -> Optional[float]:
        """從 CryptoCompare API 獲取價格"""
        symbol_upper = symbol.upper().strip()
        url = "https://min-api.cryptocompare.com/data/price"
        params = {
            'fsym': symbol_upper,
            'tsyms': 'USD'
        }

        data = self._http_get_json(url, params=params, timeout=5)
        if data and 'USD' in data:
            try:
                return float(data['USD'])
            except Exception:
                return None

        return None

    def _get_price_from_ccxt(self, normalized_symbol: str) -> Optional[float]:
        """從 CCXT 多交易所獲取價格"""
        for exchange in self.exchanges:
            try:
                ticker = exchange.fetch_ticker(normalized_symbol)
                if ticker and ticker.get('last') is not None:
                    return float(ticker['last'])
            except Exception:
                continue
        return None

    def _get_price_from_yfinance(self, symbol: str) -> Optional[float]:
        """最後備援：yfinance"""
        symbol_upper = symbol.upper().strip()

        try:
            import yfinance as yf
        except Exception:
            return None

        yahoo_symbols = [
            f"{symbol_upper}-USD",
            f"{symbol_upper}USD",
            f"{symbol_upper}-USDT",
        ]

        for yahoo_symbol in yahoo_symbols:
            try:
                ticker = yf.Ticker(yahoo_symbol)
                data = ticker.history(period="1d", interval="1m")
                if not data.empty:
                    return float(data['Close'].iloc[-1])
            except Exception:
                continue

        return None

    def get_price(self, symbol: str, asset_type: Optional[AssetType] = None) -> Optional[float]:
        """獲取加密貨幣價格（嘗試多個數據源）"""
        symbol_upper = symbol.upper().strip()
        normalized_symbol = self._normalize_symbol(symbol_upper)

        # 1. 先試交易所（CCXT）
        price = self._get_price_from_ccxt(normalized_symbol)
        if price is not None:
            return price

        # 2. 再試 Binance 公開 REST
        price = self._get_price_from_binance_rest(symbol_upper)
        if price is not None:
            return price

        # 3. 再試 CoinGecko
        price = self._get_price_from_coingecko(symbol_upper)
        if price is not None:
            return price

        # 4. 再試 CryptoCompare
        price = self._get_price_from_cryptocompare(symbol_upper)
        if price is not None:
            return price

        # 5. 最後試 yfinance
        price = self._get_price_from_yfinance(symbol_upper)
        if price is not None:
            return price

        print(f"Warning: Unable to fetch price for {symbol} from any exchange or data source")
        return None

    def get_prices(self, symbols: Dict[str, AssetType]) -> Dict[str, Optional[float]]:
        """批量獲取加密貨幣價格"""
        results = {}
        for symbol, asset_type in symbols.items():
            results[symbol] = self.get_price(symbol, asset_type)
        return results

    def supports(self, asset_type: AssetType) -> bool:
        """支援加密貨幣"""
        return asset_type == AssetType.CRYPTO