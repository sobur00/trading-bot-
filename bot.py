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
        pass  # silence default request logging


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


threading.Thread(target=run_web_server, daemon=True).start()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

PAIRS = {
    "ETC/USDT": "ETCUSDT",
    "BTC/USDT": "BTCUSDT",
    # "XAUUSD (Gold)": "PAXGUSDT",  # disabled: PAXGUSDT not trading on Binance right now, re-add when it's back
}

history = {name: deque(maxlen=60) for name in PAIRS}
last_signal = {name: "HOLD" for name in PAIRS}


def send(text, retries=2):
    for attempt in range(retries + 1):
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": text
                },
                timeout=10
            )
            return
        except Exception as e:
            print("Telegram Error:", e)
            time.sleep(2 ** attempt)


def get_price(symbol, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}",
                timeout=10
            ).json()

            if "lastPrice" not in r:
                print(f"Unexpected response for {symbol}: {r}")
                return None, None

            return float(r["lastPrice"]), float(r["priceChangePercent"])
        except Exception as e:
            print("Price Fetch Error:", symbol, e)
            time.sleep(2 ** attempt)
    return None, None


def ma(arr, n):
    a = list(arr)
    return sum(a[-n:]) / n if len(a) >= n else None


def rsi(arr, p=14):
    a = list(arr)

    if len(a) < p + 1:
        return None

    gains = 0
    losses = 0

    for i in range(-p, 0):
        diff = a[i] - a[i - 1]

        if diff > 0:
            gains += diff
        else:
            losses -= diff

    avg_gain = gains / p
    avg_loss = losses / p

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def signal(price, m5, m10, m30, r):

    if None in (m5, m10, m30, r):
        return "HOLD", "Waiting for enough data..."

    if m5 > m10 > m30 and r < 70:
        return "BUY", f"MA5>MA10>MA30 uptrend, RSI={r:.1f}"

    if m5 < m10 < m30 and r > 30:
        return "SELL", f"MA5<MA10<MA30 downtrend, RSI={r:.1f}"

    if r >= 70:
        return "HOLD", f"Overbought, RSI={r:.1f}"

    if r <= 30:
        return "HOLD", f"Oversold, RSI={r:.1f}"

    return "HOLD", "No clear trend"


print("About to send startup message", flush=True)
send("Bot Started Successfully")
print("Bot started", flush=True)

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

                print(
                    f"{datetime.now().strftime('%H:%M:%S')} | "
                    f"{name} | Price={price} | "
                    f"MA5={m5} | MA10={m10} | MA30={m30} | "
                    f"RSI={r} | Signal={sig}"
                )

                if sig != last_signal[name] and sig != "HOLD":

                    msg = (
                        f"{sig} ALERT\n\n"
                        f"Pair: {name}\n"
                        f"Price: {price}\n"
                        f"24h Change: {change}%\n"
                        f"Reason: {reason}"
                    )

                    send(msg)

                    last_signal[name] = sig

            else:
                print(f"Failed to fetch data for {name}")

        counter += 1

        if counter >= 20:

            for name in PAIRS:

                if len(history[name]):

                    send(
                        f"STATUS UPDATE\n"
                        f"{name}\n"
                        f"Price: {history[name][-1]}\n"
                        f"Signal: {last_signal[name]}"
                    )

            counter = 0

    except Exception as e:
        print("Main Loop Error:", e)

    time.sleep(10)
