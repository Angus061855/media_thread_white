import os
import re
import time
import random
import requests
from google import genai

# ── 環境變數 ──────────────────────────────────────────
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
THREADS_USER_ID    = os.environ["THREADS_USER_ID"]
THREADS_TOKEN      = os.environ["IG_ACCESS_TOKEN"]

EXAMPLE_POST = """
以下是真實的發文範例，請學習這個人的口吻、句子長度、思考方式與換行方式。
不要直接模仿句型，不要一直重複相同結構。

【範例一】
為什麼我從不叫小姐介紹小姐。

不是因為我不信任她們。

是因為這樣對介紹人不公平。

她介紹了朋友來，朋友做得好，皆大歡喜。

但萬一朋友做得不開心，她要怎麼面對那個朋友？

我見過太多姐妹情因為這種事搞僵。

所以我的規矩是，妳自己來找我，妳自己做決定。

不要讓別人的選擇，變成妳們之間的負擔。

【範例二】
有同行跟我說過，不簽合約，小姐遲早被洗走。

我聽完只有一個想法。

如果她想走，那是我做得不夠好。

小姐有領我的底薪嗎？沒有。

那憑什麼綁著她？

該是你的就會是你的，強求沒有用。
"""

WRITING_STYLES = {
    "直白觀點型": """
像一個做八大很多年的經紀人在 Threads 隨手分享自己的看法。

直接講重點，可以帶一點吐槽、質疑或反問，但不要刻意製造爭議。
語氣自然、口語，像真的在跟女生聊天，不要像老師上課，也不要像知識型文章。

可以直接講「我覺得」「我自己會」「我真的不懂」「妳仔細想」這類第一人稱觀點。
不要每一段都下結論，不需要刻意金句化，也不要一直昇華大道理。

內容要有八大從業者才會講出的實際判斷，不要只寫任何行業都適用的空泛道理。

開頭前1～2句就把核心觀點講出來。
中間用實際情況、對比、反問或簡單例子把觀點講清楚。
結尾自然收掉即可。
""",

    "黑暗面揭露型": """
專門講八大裡女生事前不容易知道的風險、話術、資訊落差與黑心經紀的操作。

開頭直接指出一個表面看起來正常，實際值得警覺的行為。

中間拆解：
這件事表面看起來是什麼。
黑心經紀可能真正想得到什麼。
女生可能在哪一步開始失去選擇權。

不要故意恐嚇，也不要把所有經紀都說成這樣。
結尾給女生一個實際可以判斷或自保的觀念。
""",

    "老經紀碎碎念型": """
像做這行很多年後，突然想到一件事情拿起手機發 Threads。

不用刻意安排完整起承轉合。
可以有「我真的不懂」「有時候看到會覺得」「反正我是這樣想啦」這種自然口語。

允許有一點抱怨、無奈、吐槽，但不要變成情緒宣洩。

內容要像真人隨手發文，不要像教科書。
結尾可以自然停住，不強制金句。
""",

    "質疑反問型": """
整篇圍繞一個「這真的合理嗎？」的問題展開。

開頭直接丟出矛盾點。
中間可以連續使用幾個自然反問，把事情的邏輯拆開。

例如對方說是福利，就問為什麼離職要還。
說自由排班，就問為什麼沒上滿天數不能領薪。

反問一定要有邏輯，不要只是嗆人。
最後可以把核心矛盾留給女生自己想。
""",

    "拆話術型": """
從八大招募或黑心經紀常見的一句話切入。

接著拆解這句話裡有哪些資訊沒講完整。
不要直接認定對方一定在騙人。

重點是幫女生翻譯：
這句話真正可能代表什麼。
還需要追問什麼。
哪些條件一定要先確認。

整篇像業內人在幫女生拆解話術，不要寫成法律文章。
""",

    "算帳型": """
不要只談感覺，直接拆利益、收入、成本或風險。

可以使用簡單數字、前後比較或實際情境。
數字要簡單易懂，不要變成財經文章。

讓女生自己看出：
表面上的高薪、福利、優惠，
跟最後真正拿到的東西可能完全不同。

結尾回到實際利益，不要寫雞湯。
""",

    "逆風觀點型": """
從一個多數人可能不認同的角度切入，但不要為了爭議硬唱反調。

直接提出自己的不同看法，再用八大的實際工作情境解釋原因。

可以承認另一邊也有合理之處。
論點一定要有理由，不要只有情緒。

結尾保留自己的立場，不需要硬說服所有人。
""",

    "業內人視角型": """
從一般女生不容易看到的經紀工作角度切入。

解釋一件事情在經紀眼裡實際怎麼運作。

可以談：
薪資。
抽成。
工作安排。
條件談判。
女生的選擇。
經紀人的利益。
市場上的實際狀況。

內容必須讓女生得到一個原本不知道的八大資訊。
不要寫任何行業都能套用的空泛職場道理。
"""
}

STYLE_NAMES = list(WRITING_STYLES.keys())


def send_telegram(message):
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    res = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": message
        },
        timeout=30
    )

    print("Telegram 狀態碼：", res.status_code)
    print("Telegram 回應：", res.text[:500])


def get_pending_topics():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    payload = {
        "filter": {
            "property": "狀態",
            "status": {
                "equals": "待發"
            }
        }
    }

    res = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    print("HTTP 狀態碼：", res.status_code)
    print("回應內容：", res.text[:500])

    data = res.json()

    results = data.get("results", [])

    print(f"待發筆數：{len(results)}")

    return results


def update_status(page_id, status="已發"):
    url = f"https://api.notion.com/v1/pages/{page_id}"

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    requests.patch(
        url,
        headers=headers,
        json={
            "properties": {
                "狀態": {
                    "status": {
                        "name": status
                    }
                }
            }
        },
        timeout=30
    )


def clean_text(text):
    text = re.sub(r'\n?-{2,}\n?', '\n', text)
    text = re.sub(r'\*{2,}', '', text)
    text = re.sub(r'(?<!\*)\*(?!\*)', '', text)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)

    lines = [
        line.strip()
        for line in text.split('\n')
    ]

    return '\n'.join(lines).strip()


def choose_style(custom_topic):
    style_list = "\n".join(
        f"- {name}"
        for name in STYLE_NAMES
    )

    prompt = f"""
請根據下面這個 Threads 主題，從指定風格中挑選最適合的一種。

【主題】
{custom_topic}

【可選風格】
{style_list}

判斷原則：
1. 涉及合約、壓薪、借貸、隱私、欺騙、PUA、控制、威脅等，優先考慮「黑暗面揭露型」或「拆話術型」
2. 涉及薪資、節薪、扣款、抽成、成本、收入比較，優先考慮「算帳型」
3. 主題本身有明顯矛盾，適合用反問拆解時，選「質疑反問型」
4. 主題是業內規則、工作方式、市場運作，選「業內人視角型」
5. 主題帶有不同於一般人的立場，選「逆風觀點型」
6. 比較生活化、感慨、經驗分享，選「老經紀碎碎念型」
7. 其他情況選「直白觀點型」

只能輸出風格名稱。
不能輸出任何解釋。
"""

    models_to_try = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
    ]

    for model in models_to_try:
        try:
            client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options={"timeout": 300000}
            )

            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            if not response.text:
                continue

            style_name = response.text.strip()

            style_name = style_name.replace("【", "").replace("】", "")
            style_name = style_name.replace('"', "").replace("'", "")
            style_name = style_name.strip()

            if style_name in WRITING_STYLES:
                print(f"🎨 AI 選擇風格：{style_name}")
                return style_name

        except Exception as e:
            print(f"⚠️ 風格判斷失敗：{e}")

    # AI 判斷失敗時 fallback
    fallback = "直白觀點型"
    print(f"⚠️ 無法判斷風格，改用：{fallback}")
    return fallback


def generate_post(custom_topic):
    style_name = choose_style(custom_topic)
    style_prompt = WRITING_STYLES[style_name]

    prompt = f"""
你是一位在八大行業做了7年的男性經紀人，現在在 Threads 上發文。

【角色】
男性。
做八大經紀7年。
像有經驗的前輩在跟女生聊天。
不高高在上。
不裝聖人。
不刻意攻擊同行。
所有問題來源只放在黑心經紀或經紀人身上，不要把問題怪到店家。

【主題】
本次主題已指定為：
「{custom_topic}」

{EXAMPLE_POST}

【本次風格：{style_name}】
{style_prompt}

【最重要的寫作要求】
一定要圍繞本次主題。
不要擅自換主題。
不要添加跟主題無關的八大知識。
不要為了湊字數硬塞大道理。

如果主題本身提供的資訊不足，
就只根據現有資訊合理延伸，
不要自行捏造真實案例、金額、人物或事件。

【字數規則】
整篇 150～200 字。
不要刻意卡死字數，但盡量落在這個範圍。

一行不超過 25 個字。
一句話太長就自然拆行。

同一個概念可以連續寫。
概念切換時再空一行。

不要每一句都空一行到像詩。

【語言風格】
使用台灣口語。

用「妳」稱呼讀者。
用「她」稱呼案例中的女生。

語氣像真人拿手機發 Threads。
可以自然使用：
「我覺得」
「我自己是」
「我真的不懂」
「妳仔細想」
「反正」
「老實說」
「有時候」

但不要每篇全部都用。

【避免 AI 味】
不要每篇都使用固定起承轉合。

不要固定用：
「真正的……」
「重點從來不是……」
「妳要找的不是……」
「這才叫……」
「說到底……」

不要每篇最後都昇華成大道理。

不要故意寫金句。

有些文章可以用提醒收尾。
有些可以用反問收尾。
有些可以直接停在個人立場。
有些可以自然結束。

【寫作規則】
1. 禁止使用任何人名
2. 案例人物一律使用「有個小姐」「有個女生」「她」
3. 禁止 emoji
4. 禁止粗體、斜體、Markdown
5. 標點符號使用全形（，。？！：）
6. 禁止使用「不是⋯而是⋯」句型
7. 禁止使用「姐妹們」「姊妹們」「妹子」「進場」
8. 不要把店家寫成問題來源
9. 不要編造我本人沒說過的經歷
10. 不要寫標題
11. 不要輸出「本次風格」
12. 不要輸出任何說明
13. 直接輸出可以發布到 Threads 的正文
"""

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
    ]

    for model in models_to_try:
        print(f"🤖 使用模型：{model}")

        for attempt in range(3):
            try:
                print(f"  第 {attempt + 1} 次呼叫 Gemini...")

                client = genai.Client(
                    api_key=GEMINI_API_KEY,
                    http_options={"timeout": 300000}
                )

                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )

                if not response.text:
                    print("  回應為空，重試...")
                    continue

                cleaned = clean_text(
                    response.text.strip()
                )

                print(
                    f"📋 前100字：{repr(cleaned[:100])}"
                )

                return cleaned, style_name

            except Exception as e:
                err = str(e)

                print(
                    f"  第 {attempt + 1} 次失敗：{err}"
                )

                if "503" in err:
                    wait = 2 ** attempt * 10

                    print(
                        f"  503 過載，等 {wait} 秒..."
                    )

                    time.sleep(wait)

                elif "429" in err:
                    print(
                        "  429 額度已滿，換下一個模型"
                    )

                    break

                else:
                    raise

        print(
            f"  {model} 全部失敗，換下一個模型..."
        )

    raise Exception(
        "所有模型都失敗，放棄"
    )


def post_to_threads(text):
    text = clean_text(text)

    if len(text) > 500:
        text = text[:500]

    print(
        f"🚀 建立發文（{len(text)} 字元）"
        f" | 預覽：{repr(text[:60])}"
    )

    create_url = (
        f"https://graph.threads.net/v1.0/"
        f"{THREADS_USER_ID}/threads"
    )

    data = {
        "media_type": "TEXT",
        "text": text,
        "access_token": THREADS_TOKEN
    }

    res = requests.post(
        create_url,
        data=data,
        timeout=30
    ).json()

    creation_id = res.get("id")

    if not creation_id:
        raise Exception(
            f"建立 container 失敗：{res}"
        )

    time.sleep(8)

    for attempt in range(3):
        print(
            f"📤 發布（第 {attempt + 1} 次）..."
        )

        pub_res = requests.post(
            (
                f"https://graph.threads.net/v1.0/"
                f"{THREADS_USER_ID}/threads_publish"
            ),
            data={
                "creation_id": creation_id,
                "access_token": THREADS_TOKEN
            },
            timeout=30
        ).json()

        if pub_res.get("id"):
            print(
                f"✅ 發布成功：{pub_res['id']}"
            )
            return

        elif pub_res.get(
            "error",
            {}
        ).get(
            "is_transient"
        ):
            print(
                "暫時性錯誤，等待 15 秒..."
            )

            time.sleep(15)

        else:
            raise Exception(
                f"發布失敗：{pub_res}"
            )

    raise Exception(
        "發布失敗超過重試次數"
    )


if __name__ == "__main__":
    print("=== White 7 自動生成 ===")

    pages = get_pending_topics()

    if not pages:
        print(
            "沒有待發主題，結束。"
        )

        send_telegram(
            "⚠️ White 7 今日無待發主題"
        )

        exit(0)

    page = random.choice(pages)
    page_id = page["id"]

    props = page.get(
        "properties",
        {}
    )

    topic_list = props.get(
        "主題",
        {}
    ).get(
        "title",
        []
    )

    custom_topic = (
        topic_list[0]["plain_text"]
        if topic_list
        else ""
    )

    if not custom_topic.strip():
        print(
            "主題為空，這筆跳過。"
        )

        update_status(
            page_id,
            "失敗"
        )

        send_telegram(
            "❌ White 7 抽到空白主題，已標記失敗"
        )

        exit(0)

    try:
        print(
            f"📌 主題：{custom_topic}"
        )

        post_text, style_name = generate_post(
            custom_topic
        )

        print(
            f"🎨 最終風格：{style_name}"
        )

        print(
            "貼文內容：\n",
            post_text
        )

        post_to_threads(
            post_text
        )

        update_status(
            page_id,
            "已發"
        )

        print(
            "✅ 完成！"
        )

        send_telegram(
            f"✅ White 7 發文成功！"
            f"\n風格：{style_name}"
            f"\n主題：{custom_topic}"
        )

    except Exception as e:
        error_msg = (
            f"❌ White 7 發文失敗！"
            f"\n主題：{custom_topic}"
            f"\n錯誤原因：{str(e)}"
        )

        print(
            error_msg
        )

        update_status(
            page_id,
            "失敗"
        )

        send_telegram(
            error_msg
        )

        raise
