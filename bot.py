import requests, time, os, threading
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

SYMBOL = "ETCUSDT"
NAME = "ETC/USDT"

history = deque(maxlen=60)
last_signal = "HOLD"

# Track signal history over time for percentage breakdown
# 30s per cycle, 3 hours = 360 readings
SIGNAL_WINDOW = 360
signal_history = deque(maxlen=SIGNAL_WINDOW)


def signal_percentages():
    if not signal_history:
        return None
    total = len(signal_history)
    buy_pct = (signal_history.count("BUY") / total) * 100
    sell_pct = (signal_history.count("SELL") / total) * 100
    hold_pct = (signal_history.count("HOLD") / total) * 100
    hours_covered = (total * 30) / 3600
    return buy_pct, sell_pct, hold_pct, hours_covered


def send(text):
    try:
        requests.post(
            "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass


def get_price():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ethereum-classic", "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10
        ).json()
        price = float(r["ethereum-classic"]["usd"])
        change = float(r["ethereum-classic"].get("usd_24h_change", 0))
        return price, change
    except:
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


send("Bot Started! Now tracking ETC/USDT. Building data, wait 2 minutes for first signals.")
print("Bot started - ETC/USDT only")
counter = 0

while True:
    try:
        price, change = get_price()
        if price:
            history.append(price)
            m5 = ma(history, 5)
            m10 = ma(history, 10)
            m30 = ma(history, 30)
            r = rsi(history)
            sig, reason = signal(price, m5, m10, m30, r)
            signal_history.append(sig)
            rtxt = str(round(r, 1)) if r else "..."
            print(datetime.now().strftime("%H:%M:%S") + " " + NAME + " price=" + str(price) + " signal=" + sig + " rsi=" + rtxt)

            if sig != last_signal and sig != "HOLD":
                label = "BUY ALERT" if sig == "BUY" else "SELL ALERT"
                msg = label + " " + NAME + "\nPrice: " + str(round(price, 4)) + "\nChange: " + str(round(change, 2)) + "%\nReason: " + reason

                pct = signal_percentages()
                if pct:
                    buy_pct, sell_pct, hold_pct, hours = pct
                    msg += "\n\nLast " + str(round(hours, 1)) + "h breakdown:\nBUY: " + str(round(buy_pct, 1)) + "%\nSELL: " + str(round(sell_pct, 1)) + "%\nHOLD: " + str(round(hold_pct, 1)) + "%"

                msg += "\nOpen Will Trade and " + sig + " now!"
                send(msg)
            last_signal = sig
        else:
            print("Failed to fetch price")

        counter += 1
        if counter >= 20:
            if len(history) > 0:
                msg = "Update " + NAME + " price " + str(round(history[-1], 4)) + " signal " + last_signal

                pct = signal_percentages()
                if pct:
                    buy_pct, sell_pct, hold_pct, hours = pct
                    msg += "\n\nLast " + str(round(hours, 1)) + "h breakdown:\nBUY: " + str(round(buy_pct, 1)) + "%\nSELL: " + str(round(sell_pct, 1)) + "%\nHOLD: " + str(round(hold_pct, 1)) + "%"

                send(msg)
            counter = 0

    except Exception as e:
        print("Error: " + str(e))

    time.sleep(30)
