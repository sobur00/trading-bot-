import sys
import requests, time, os, threading
sys.stdout.reconfigure(line_buffering=True)
print("SCRIPT STARTED - top of file", flush=True)
from datetime import datetime
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler


class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


threading.Thread(target=run_web_server, daemon=True).start()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

PAIRS = {
    "ETC/USDT": "ETCUSDT",
    "XAUUSD (Gold)": "PAXGUSDT"
}

# CoinGecko IDs for primary price source
COINGECKO_IDS = {
    "ETCUSDT": "ethereum-classic",
    "PAXGUSDT": "pax-gold",
}

# CoinCap IDs for fallback price source (not geo-blocked like Binance)
COINCAP_IDS = {
    "ETCUSDT": "ethereum-classic",
    "PAXGUSDT": "pax-gold",
}

history = {name: deque(maxlen=60) for name in PAIRS}
last_signal = {name: "HOLD" for name in PAIRS}


def send(text):
    try:
        requests.post(
            "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print("Telegram Error:", e)


def get_price_coingecko(symbol):
    coin_id = COINGECKO_IDS.get(symbol)
    if not coin_id:
        return None, None
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10
        )
        if resp.status_code == 429:
            print(f"CoinGecko rate limited on {symbol}")
            return None, None

        r = resp.json()
        if coin_id not in r or "usd" not in r[coin_id]:
            print(f"Unexpected CoinGecko response for {symbol}: {r}")
            return None, None

        price = float(r[coin_id]["usd"])
        change = float(r[coin_id].get("usd_24h_change", 0))
        return price, change
    except Exception as e:
        print("CoinGecko Fetch Error:", symbol, e)
        return None, None


def get_price_coincap(symbol):
    asset_id = COINCAP_IDS.get(symbol)
    if not asset_id:
        return None, None
    try:
        resp = requests.get(
            f"https://api.coincap.io/v2/assets/{asset_id}",
            timeout=10
        )
        if resp.status_code != 200:
            print(f"CoinCap error on {symbol}: status {resp.status_code}")
            return None, None

        r = resp.json().get("data", {})
        price = float(r["priceUsd"])
        change = float(r.get("changePercent24Hr", 0) or 0)
        return price, change
    except Exception as e:
        print("CoinCap Fetch Error:", symbol, e)
        return None, None


def get_price(symbol):
    price, change = get_price_coingecko(symbol)
    if price is not None:
        return price, change

    print(f"Falling back to CoinCap for {symbol}")
    price, change = get_price_coincap(symbol)
    if price is not None:
        return price, change

    return None, None


def ma(arr, n):
    a = list(arr)
    return sum(a[-n:]) / n if len(a) >= n else None


def rsi(arr, p=14):
    a = list(arr)
    if len(a) < p + 1:
        return None
    g = 0
    l = 0
    for i in range(-p, 0):
        d = a[i] - a[i - 1]
        if d > 0:
            g += d
        else:
            l -= d
    ag = g / p
    al = l / p
    if al == 0:
        return 100
    return 100 - (100 / (1 + (ag / al)))


def signal(price, m5, m10, m30, r):
    if not all([m5, m10, m30]) or r is None:
        return "HOLD", "Building data..."
    bull = price > m5 and m5 > m10 and m10 > m30
    bear = price < m5 and m5 < m10 and m10 < m30
    if bull and r < 32:
        return "BUY", "Price above all MAs plus RSI oversold"
    if bull and r < 50:
        return "BUY", "Bullish MA alignment"
    if bear and r > 68:
        return "SELL", "Price below all MAs plus RSI overbought"
    if bear and r > 55:
        return "SELL", "Bearish MA stack"
    if r < 32 and price > m10:
        return "BUY", "RSI oversold plus above MA10"
    if r > 68 and price < m10:
        return "SELL", "RSI overbought plus below MA10"
    return "HOLD", "Watching..."


send("Bot Started! Now tracking ETC/USDT and XAUUSD (Gold). Building data, wait 2 minutes for first signals.")
print("Bot started - dual pair mode", flush=True)
counter = 0

while True:
    try:
        for name, symbol in PAIRS.items():
            price, change = get_price(symbol)
            if price:
                history[name].append(price)
                m5 = ma(history[name], 5)
                m10 = ma(history[name], 10)
                m30 = ma(history[name], 30)
                r = rsi(history[name])
                sig, reason = signal(price, m5, m10, m30, r)
                rtxt = str(round(r, 1)) if r else "..."
                print(datetime.now().strftime("%H:%M:%S") + " " + name + " price=" + str(price) + " signal=" + sig + " rsi=" + rtxt)

                if sig != last_signal[name] and sig != "HOLD":
                    label = "BUY ALERT" if sig == "BUY" else "SELL ALERT"
                    msg = label + " " + name + "\nPrice: " + str(round(price, 4)) + "\nChange: " + str(round(change, 2)) + "%\nReason: " + reason + "\nOpen Will Trade and " + sig + " now!"
                    send(msg)
                last_signal[name] = sig
            else:
                print(f"Failed to fetch data for {name}")

            # Space out requests between pairs to avoid rate limits
            time.sleep(5)

        counter += 1
        if counter >= 20:
            for name, symbol in PAIRS.items():
                if len(history[name]) > 0:
                    p = history[name][-1]
                    send("Update " + name + " price " + str(round(p, 4)) + " signal " + last_signal[name])
            counter = 0

    except Exception as e:
        print("Error: " + str(e))

    time.sleep(60)
