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


def fetch_latest(item):
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
    latest = None
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"], recursive=False)
            values = [cell.get_text(" ", strip=True) for cell in cells]

            if len(values) < 5:
                continue

            try:
                row_date = datetime.strptime(values[0], "%Y/%m/%d").date()
                numbers = [int(value.replace(",", "")) for value in values[1:5]]
            except ValueError:
                continue

            # GitHub 的排程可能延到午夜後；使用網頁上最新已公布的交易日。
            if row_date > datetime.now(TZ).date():
                continue
            if latest is None or row_date > latest[0]:
                latest = (row_date, {
                    "date": row_date.strftime("%Y/%m/%d"),
                    "buy": numbers[0],
                    "sell": numbers[1],
                    "net": numbers[3],
                })

    return latest[1] if latest else None


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

    results = []

    for item in items:
        result = fetch_latest(item)
        if result is None:
            print(f'{item["stock_name"]}：查無已公布的分點資料，跳過')
            continue
        results.append((item, result))

    if not results:
        print("查無已公布的分點資料，不傳 Telegram")
        return

    # 各分點可能因資料更新時間不同而有日期差；只發送共同的最新資料日。
    report_date = max(result["date"] for _, result in results)
    report_lines = []

    for item, result in results:
        if result["date"] != report_date:
            print(f'{item["stock_name"]}：資料日 {result["date"]} 較舊，跳過')
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
        print(f"{report_date} 追蹤的分點都沒有買賣，不傳 Telegram")
        return

    title = f"📊 關鍵分點日報 資料日 {report_date.replace('/', '-')}"
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
