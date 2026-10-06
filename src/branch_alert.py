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

    for item in items:
        result = fetch_today(item)

        if result is None:
            print(f'{item["stock_name"]}：今天沒有資料，跳過')
            continue

        print(
            f'{item["stock_name"]}｜{item["branch_name"]}：'
            f'買進 {result["buy"]} 張、'
            f'賣出 {result["sell"]} 張、'
            f'買賣超 {result["net"]:+,} 張'
        )

        if result["buy"] == 0 and result["sell"] == 0:
            print("今天沒有買賣，不傳 Telegram")
            continue

        message = (
            f'{result["date"]} {item["stock_name"]}（{item["stock_id"]}）'
            f'｜{item["branch_name"]}\n'
            f'買進：{result["buy"]:,} 張\n'
            f'賣出：{result["sell"]:,} 張\n'
            f'買賣超：{result["net"]:+,} 張'
        )
        send_telegram(message)
        print("Telegram 已送出")


if __name__ == "__main__":
    main()