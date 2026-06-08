import os
import re
import time
import random
import requests
from google import genai

# ── 環境變數 ──────────────────────────────────────────
NOTION_TOKEN_2       = os.environ["NOTION_TOKEN_2"]
NOTION_PENDING_DB_ID = os.environ["NOTION_DATABASE_ID_2"]
GEMINI_API_KEY       = os.environ["GEMINI_API_KEY"]
THREADS_USER_ID      = os.environ["THREADS_USER_ID"]
THREADS_TOKEN        = os.environ["IG_ACCESS_TOKEN"]

EXAMPLE_POSTS = """
以下是真實的發文範例，請完全學習這個風格、語氣、句子長度和換行方式：

【範例第一則】
短影音或IG真的不要再讓小姐入鏡了好嗎。

我知道流量密碼真的都是拍到小姐，我也不管小姐是否同意，畢竟也許小姐當下覺得這行業很好玩，所以同意出鏡。

但過陣子呢。

他們說不定改變想法，想去做一般行業，被身邊認識的人認出來該怎麼辦，你們有想過嗎。

就算打馬賽克還是戴著一半的面具，身上的特徵也很容易找到的。

現在網友真的很厲害，有一點資訊都可以肉搜出來。

【範例第二則】
上個月，有個小姐跑來找我，她說她之前跟她經紀拍了幾支短影音。

她說她那時候覺得很新鮮，而且她經紀跟她說會打馬賽克，不會被認出來。

結果影片發出去之後，不到一個禮拜，她就被她高中同學認出來了。

她說她同學傳訊息給她，問她是不是在做酒店，她當下整個傻眼。

她說她那時候根本不知道該怎麼回，因為她根本沒想到會被認出來。

後來她才發現，她手上有個很明顯的小刺青，而且她的體型跟髮型都很有特色。

她同學就是靠這些特徵認出她的。

【範例第三則】
她跟我說，哥我現在真的很後悔，因為我根本沒想到會這樣。

她說她現在每天都活在恐懼中，怕被更多人認出來，怕被家人發現。

她說她經紀還在那邊沾沾自喜，說那支影片帶了好幾個妹，賺了多少錢。

但她呢，一輩子就這樣被掛上八大小姐的稱號。

她說她問她經紀能不能把影片刪掉，結果她經紀跟她說，影片已經被轉發那麼多次了，刪掉也沒用。

她跟我說，哥我真的很想哭，因為我覺得我的人生就這樣毀了。
"""

def send_telegram(message):
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=30
    )

def get_pending_topics():
    print("開始呼叫 Notion API...")
    url = f"https://api.notion.com/v1/databases/{NOTION_PENDING_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN_2}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {"filter": {"property": "狀態", "status": {"equals": "待發"}}}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        print("HTTP 狀態碼：", res.status_code)
        data = res.json()
        results = data.get("results", [])
        print("找到筆數：", len(results))
        return results
    except Exception as e:
        print("❌ 錯誤：", str(e))
        return []

def update_status(page_id, status="已發"):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN_2}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    requests.patch(url, headers=headers, json={"properties": {"狀態": {"status": {"name": status}}}}, timeout=30)

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
        if len(posts) >= 3:
            return posts

    if re.search(r'\*{0,2}第[一二三四五六七八九十\d]+則\*{0,2}', content):
        posts = re.split(r'\*{0,2}第[一二三四五六七八九十\d]+則\*{0,2}', content)
        posts = [p.strip() for p in posts if p.strip()]
        if len(posts) >= 3:
            return posts

    if re.search(r'^\d+[\.、．]\s', content, re.MULTILINE):
        posts = re.split(r'^\d+[\.、．]\s', content, flags=re.MULTILINE)
        posts = [p.strip() for p in posts if p.strip()]
        if len(posts) >= 3:
            return posts

    return []

def contains_person_name(text):
    names = re.findall(r'(?<![.!?。！？\n])\b[A-Z][a-z]{1,10}\b', text)
    if names:
        print(f"⚠️ 偵測到疑似英文人名：{names}")
        return True
    return False

def validate_output(text):
    posts = split_posts(text)
    if len(posts) < 3:
        section_count = text.count('§')
        return False, f"切割失敗：只切出 {len(posts)} 則，§ 出現 {section_count} 次。前200字：{repr(text[:200])}"
    if contains_person_name(text):
        return False, "包含英文人名"
    return True, None

def generate_post(custom_topic):
    prompt = f"""
你是一位在八大行業做了7年的男性經紀人，現在在 Threads 上連續發文，目的是幫助想入行或已經在行業裡的女生保護自己、避免被黑心經紀騙。

【主題】
本次主題已指定為：「{custom_topic}」
請直接用這個主題寫文章，不需要自己想題材。

{EXAMPLE_POSTS}

【角色設定】
- 性別：男，身份：八大經紀人，做了7年
- 口吻：像有經驗的前輩在跟朋友說話，不說教、不高高在上
- 所有問題的來源只有一個：黑心經紀人，跟店家無關，不要提店家

【文章結構】5到7則，最多七則

第一則：衝擊性開場，打破常見認知，製造懸念
第二則：具體案例故事，帶出真實情境
第三則：深化觀點，延續案例，說明後果與心情
第四則：解釋現象背後的原因和機制
第五則：實用建議或行動指南
第六則：第二個案例或強化論點
第七則：收尾昇華，引導留言或私訊（不要用「姐妹們」開頭）

【字數規則】每則 200-280 個中文字，絕對不要超過 280 字
一行不超過25個字。同一概念不空行，只有概念切換才空一行。

【語言風格】
台灣口語，每句獨立一行，句號後換行。
用「妳」稱呼讀者，用「她」稱呼案例中的人。
對話格式：「我問她，○○？」「她說，○○。」

【寫作規則】
1. 【絕對禁止】使用任何人名，包含英文名如 Katie、Amy、Lisa，一律用「有個小姐」「有個女生」「她」代替
2. 禁止 emoji、粗體、斜體
3. 標點符號全部使用全形（，。？！：）
4. 禁止 AI 感用語、禁止「不是⋯而是⋯」句型
5. 問題來源只能是「黑心經紀」或「經紀人」
6. 禁止「姐妹們」「姊妹們」「妹子」「進場」

【§ 格式規則 ── 最重要，必須嚴格遵守】

輸出格式範例如下，必須完全照做：

主題：{custom_topic}

§1
（第一則內容）

§2
（第二則內容）

§3
（第三則內容）

規則：
- §符號後面直接接數字，中間絕對不可有空格，不可有星號
- §那一行只能有§和數字，不能有其他任何文字
- 禁止輸出 ---、***、** 等任何 Markdown 符號
- 直接輸出內容，不要加說明文字

【情緒曲線】
第一則：震撼 → 第二則：同情 → 第三則：憤怒 → 第四則：恐懼 → 第五則：希望＋警惕 → 第六則：強化警惕 → 第七則：信任＋行動呼籲
"""

    for attempt in range(5):
        try:
            print(f"🤖 第 {attempt+1} 次呼叫 Gemini...")
            client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options={"timeout": 300000}
            )
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            raw = response.text.strip()
            cleaned = clean_text(raw)

            print(f"📋 § 出現次數：{cleaned.count('§')}")
            print(f"📋 前200字：{repr(cleaned[:200])}")

            ok, reason = validate_output(cleaned)
            if not ok:
                print(f"⚠️ 第 {attempt+1} 次不合格：{reason}")
                if attempt < 4:
                    wait = 15 * (attempt + 1)
                    print(f"等待 {wait} 秒後重試...")
                    time.sleep(wait)
                    continue
                else:
                    raise Exception(f"Gemini 連續 5 次不合格，最後原因：{reason}")

            return cleaned

        except Exception as e:
            print(f"第 {attempt+1} 次失敗：{e}")
            if attempt < 4:
                time.sleep(30)
            else:
                raise

def add_line_spacing(text):
    """
    每句話結尾（句號、！、？）後面自動加空行，
    逗號結尾的連續句子保持在一起不拆開。
    """
    lines = text.split('\n')
    result = []
    for i, line in enumerate(lines):
        result.append(line)
        if i < len(lines) - 1:
            current_ends_with_punct = line and line[-1] in '。！？'
            next_line = lines[i + 1]
            next_is_empty = next_line.strip() == ''
            if current_ends_with_punct and not next_is_empty:
                result.append('')
    return '\n'.join(result)

def post_to_threads(post_text):
    post_text = post_text.strip()

    # 直接從第一個 § 開始，丟掉前面所有主題備註文字
    first_section = post_text.find('§')
    if first_section == -1:
        # 沒有 §，才用舊的逐行跳過邏輯
        lines = post_text.split("\n")
        content_lines = []
        skip_topic = True
        for line in lines:
            if skip_topic and line.startswith("主題："):
                skip_topic = False
                continue
            content_lines.append(line)
        content = "\n".join(content_lines).strip()
    else:
        content = post_text[first_section:].strip()

    posts = split_posts(content)
    if len(posts) < 3:
        raise Exception(f"段落切割異常，只切出 {len(posts)} 則。\n內容前300字：\n{content[:300]}")

    print(f"📝 共 {len(posts)} 則，準備發文...")
    last_published_id = ""

    for i, text in enumerate(posts):
        text = clean_text(text)
        text = text.replace("\\n", "\n")
        text = add_line_spacing(text)
        text = truncate_to_chars(text, max_chars=480)

        if not text:
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
    print("=== _2 給主題自動發模式 ===")
    pages = get_pending_topics()
    if not pages:
        print("沒有待發主題，結束。")
        exit(0)

    page = random.choice(pages)
    page_id = page["id"]
    props = page.get("properties", {})
    topic_list = props.get("主題", {}).get("title", [])
    custom_topic = topic_list[0]["plain_text"] if topic_list else ""

    if not custom_topic.strip():
        print("主題為空，結束。")
        update_status(page_id, "已發")
        exit(0)

    try:
        print(f"📌 主題：{custom_topic}")
        post_text = generate_post(custom_topic)
        print("貼文內容：\n", post_text)
        post_to_threads(post_text)
        update_status(page_id, "已發")
        print("✅ 完成！")
        send_telegram(f"✅ Thread White 2 給主題 發文成功！\n主題：{custom_topic}")
    except Exception as e:
        error_msg = f"❌ media 給主題 發文失敗！\n錯誤原因：{str(e)}"
        print(error_msg)
        send_telegram(error_msg)
        raise
