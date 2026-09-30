import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _get_price_from_coingecko(symbol: str):
    symbol_map = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "AR": "arweave",
        "TAO": "bittensor",
        "DOT": "polkadot",
        "ASTR": "astar",
    }

    coin_id = symbol_map.get(symbol.upper())
    if not coin_id:
        return None

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coin_id, "vs_currencies": "usd"}

    try:
        r = requests.get(url, params=params, timeout=10, verify=False)
        r.raise_for_status()
        data = r.json()
        if coin_id in data and "usd" in data[coin_id]:
            return float(data[coin_id]["usd"])
    except Exception as e:
        print(f"[coingecko] failed for {symbol}: {type(e).__name__}: {e}")

    return None

print(_get_price_from_coingecko("AR"))
print(_get_price_from_coingecko("TAO"))