import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Taipei")
WATCHLIST_PATH = "src/watchlist.json"
BASE_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco0/zco0.djhtm"


def read_watchlist():
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as file:
        return json.load(file).get("items", [])


def make_branch_code(branch_code):
    return "".join(f"{ord(char):04X}" for char in branch_code)


def fetch_today(item):
    response = requests.get(
        BASE_URL,
        params={
            "a": item["stock_id"],
            "b": make_branch_code(item["branch_code"]),
            "BHID": item["broker_code"],
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    today = datetime.now(TZ).strftime("%Y/%m/%d")

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            values = [cell.get_text(" ", strip=True) for cell in cells]

            if len(values) < 5 or values[0] != today:
                continue

            numbers = [int(value.replace(",", "")) for value in values[1:5]]
            return {
                "date": today,
                "buy": numbers[0],
                "sell": numbers[1],
                "net": numbers[3],
            }

    return None


def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError("GitHub Secrets 尚未提供 Telegram 設定")

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=20,
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram 傳送失敗：{result}")


def main():
    items = read_watchlist()
    if not items:
        raise ValueError("watchlist.json 裡沒有追蹤項目")

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    report_lines = []

    for item in items:
        result = fetch_today(item)

        if result is None:
            print(f'{item["stock_name"]}：今天沒有資料，跳過')
            continue

        if result["buy"] == 0 and result["sell"] == 0:
            print(f'{item["stock_name"]}：今天沒有買賣，跳過')
            continue

        if result["net"] > 0:
            icon = "🟢"
        elif result["net"] < 0:
            icon = "🔴"
        else:
            icon = "⚪"

        line = (
            f'{icon} {item["stock_name"]}（{item["stock_id"]}）'
            f'｜{item["branch_name"]} '
            f'買 {result["buy"]:,}／賣 {result["sell"]:,}／'
            f'淨 {result["net"]:+,} 張'
        )
        report_lines.append(line)
        print(line)

    if not report_lines:
        print("今天追蹤的分點都沒有買賣，不傳 Telegram")
        return

    title = f"📊 關鍵分點日報 {today}"
    messages = []
    current_message = title

    for line in report_lines:
        addition = f"\n\n{line}"

        # 保留長度空間，避免超過 Telegram 單則訊息上限
        if len(current_message) + len(addition) > 3900:
            messages.append(current_message)
            current_message = f"{title}（續）"
            addition = f"\n\n{line}"

        current_message += addition

    messages.append(current_message)

    for message in messages:
        send_telegram(message)

    print(f"Telegram 日報已送出，共 {len(messages)} 則")
if __name__ == "__main__":
    main()
