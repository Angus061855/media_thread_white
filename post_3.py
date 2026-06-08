import os
import re
import time
import random
import requests

# ── 環境變數 ──────────────────────────────────────────
NOTION_TOKEN_2     = os.environ["NOTION_TOKEN_2"]
NOTION_POST_DB_ID  = os.environ["NOTION_DATABASE_ID_3"]
THREADS_USER_ID    = os.environ["THREADS_USER_ID"]
THREADS_TOKEN      = os.environ["IG_ACCESS_TOKEN"]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN_2}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def send_telegram(message):
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=30
    )

def clean_text(text):
    text = re.sub(r'\n?-{2,}\n?', '\n', text)
    text = re.sub(r'\*{2,}', '', text)
    text = re.sub(r'(?<!\*)\*(?!\*)', '', text)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [line.strip() for line in text.split('\n')]
    return '\n'.join(lines).strip()

def truncate_to_chars(text, max_chars=480):
    text = text.strip()
    if len(text) <= max_chars:
        if text and text[-1] not in '。！？':
            for punct in ['。', '！', '？']:
                idx = text.rfind(punct)
                if idx > len(text) * 0.5:
                    return text[:idx + 1]
        return text
    truncated = text[:max_chars]
    last_break = -1
    for punct in ['。', '！', '？']:
        idx = truncated.rfind(punct)
        if idx > last_break:
            last_break = idx
    if last_break > max_chars * 0.6:
        return truncated[:last_break + 1]
    idx = truncated.rfind('\n')
    if idx > max_chars * 0.6:
        return truncated[:idx]
    return truncated

def split_posts(content):
    """
    多層 fallback 切割，支援 Gemini 各種輸出格式：
    1. § 符號（各種變體）
    2. 第X則（中文數字）
    3. 數字+點（1. 2. 3.）
    """
    if '§' in content:
        content_mod = re.sub(
            r'\*{0,3}\s*§\s*([０-９\d]+)\s*\*{0,3}',
            r'\n§SPLIT§\1\n',
            content
        )
        parts = content_mod.split('\n§SPLIT§')
        posts = []
        for part in parts:
            lines = part.split('\n')
            if lines and re.match(r'^[０-９\d]+$', lines[0].strip()):
                lines = lines[1:]
            text = '\n'.join(lines).strip()
            if text:
                posts.append(text)
        if len(posts) >= 2:
            return posts

    if re.search(r'\*{0,2}第[一二三四五六七八九十\d]+則\*{0,2}', content):
        posts = re.split(r'\*{0,2}第[一二三四五六七八九十\d]+則\*{0,2}', content)
        posts = [p.strip() for p in posts if p.strip()]
        if len(posts) >= 2:
            return posts

    if re.search(r'^\d+[\.、．]\s', content, re.MULTILINE):
        posts = re.split(r'^\d+[\.、．]\s', content, flags=re.MULTILINE)
        posts = [p.strip() for p in posts if p.strip()]
        if len(posts) >= 2:
            return posts

    return []

def normalize_content_format(content):
    """
    Notion rich_text 讀出來如果沒有換行，
    根據全形標點自動補換行，每句獨立一行。
    """
    content = clean_text(content)

    # 如果已有 § 分隔符號，格式正常直接返回
    if '§' in content:
        return content

    # 在全形標點後補換行
    content = re.sub(r'([。！？])\s*(?!\n)', r'\1\n', content)
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()

def get_pending_posts():
    url = f"https://api.notion.com/v1/databases/{NOTION_POST_DB_ID}/query"
    payload = {"filter": {"property": "狀態", "status": {"equals": "待發"}}}
    res = requests.post(url, headers=NOTION_HEADERS, json=payload, timeout=30)
    print("HTTP 狀態碼：", res.status_code)
    data = res.json()
    if data.get("object") == "error":
        print("❌ API 錯誤：", data)
        return []
    results = data.get("results", [])
    print(f"篩選後待發筆數：{len(results)}")
    return results

def get_content_from_property(page):
    rich_text = page["properties"].get("內容", {}).get("rich_text", [])
    content = "".join([t["plain_text"] for t in rich_text])
    print(f"✅ 讀到內容，長度：{len(content)}")
    return content

def update_status(page_id, status="已發"):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    requests.patch(
        url,
        headers=NOTION_HEADERS,
        json={"properties": {"狀態": {"status": {"name": status}}}},
        timeout=30
    )

def post_to_threads(content):
    content = clean_text(content)
    content = normalize_content_format(content)

    posts = split_posts(content)
    print(f"📝 共分成 {len(posts)} 則發文")

    if len(posts) < 2:
        raise Exception(
            f"段落切割失敗，只切出 {len(posts)} 則，"
            f"內容預覽：{repr(content[:300])}"
        )

    last_published_id = ""

    for i, text in enumerate(posts):
        text = text.replace("\\n", "\n")
        text = truncate_to_chars(text, 480)

        if not text.strip():
            print(f"⚠️ 第 {i+1} 則內容為空，跳過")
            continue

        print(f"🚀 建立第 {i+1} 則（{len(text)} 字元）| 預覽：{repr(text[:60])}")

        create_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
        data = {"media_type": "TEXT", "text": text, "access_token": THREADS_TOKEN}
        if last_published_id:
            data["reply_to_id"] = last_published_id

        res = requests.post(create_url, data=data, timeout=30).json()
        creation_id = res.get("id")
        if not creation_id:
            raise Exception(f"建立 container 失敗（第 {i+1} 則）：{res}")
        time.sleep(8)

        pub_res = None
        for attempt in range(3):
            print(f"📤 發布第 {i+1} 則（第 {attempt+1} 次）...")
            pub_res = requests.post(
                f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish",
                data={"creation_id": creation_id, "access_token": THREADS_TOKEN},
                timeout=30
            ).json()
            if pub_res.get("id"):
                break
            elif pub_res.get("error", {}).get("is_transient"):
                print(f"暫時性錯誤，等待 15 秒...")
                time.sleep(15)
            else:
                raise Exception(f"發布失敗（第 {i+1} 則）：{pub_res}")

        if not pub_res or not pub_res.get("id"):
            raise Exception(f"發布失敗超過重試次數（第 {i+1} 則）：{pub_res}")

        last_published_id = pub_res.get("id", "")
        print(f"✅ 第 {i+1} 則發布成功：{last_published_id}")

        wait = random.randint(10, 20)
        print(f"⏳ 等待 {wait} 秒後發下一則...")
        time.sleep(wait)

if __name__ == "__main__":
    print("=== _3 段落直接發模式 ===")

    posts = get_pending_posts()
    if not posts:
        print("沒有待發內容，結束。")
        exit(0)

    valid_posts = []
    for page in posts:
        content = get_content_from_property(page)
        if content.strip():
            valid_posts.append((page, content))

    if not valid_posts:
        print("所有待發筆內容都是空的，結束。")
        exit(0)

    target_page, target_content = random.choice(valid_posts)
    page_id = target_page["id"]
    print(f"🎲 隨機選中（共 {len(valid_posts)} 筆有內容）")
    print(f"讀到的內容預覽：{repr(target_content[:200])}")

    try:
        print("📄 找到待發內容，開始發文...")
        post_to_threads(target_content)
        update_status(page_id, "已發")
        print("✅ 完成！")
        send_telegram("✅ Thread White 3 給文章 發文成功！")
    except Exception as e:
        error_msg = f"❌ Thread White 3 給文章 發文失敗！\n錯誤原因：{str(e)}"
        print(error_msg)
        send_telegram(error_msg)
        raise
