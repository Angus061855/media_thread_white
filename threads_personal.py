"""Personal Notion -> Threads publisher. Default: read-only preflight.

Run this through the supplied serialized GitHub workflow, not multiple runners.
Unfinished publication blocks the queue until manually reconciled.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib import error, parse, request

READY = "新程式待發"
BUSY = "發布中"
DONE = "已發"
CONTENT = "預寫內容"
JOURNAL = "發文紀錄"


class Stop(Exception):
    pass


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise Stop(f"缺少設定：{name}")
    return value


def http(method, url, headers, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except error.HTTPError as exc:
        # Never print API response bodies, URLs containing secrets, or tokens.
        raise Stop(f"API HTTP {exc.code}；已停止，不自動重試。") from None
    except (error.URLError, TimeoutError, OSError, ValueError):
        raise Stop("連線逾時或回應無法判讀；結果可能不明，已停止。") from None


def split_posts(text):
    text = text.replace("\r\n", "\n").strip()
    markers = list(re.finditer(r"(?m)^§([1-9][0-9]*)[ \t]*$", text))
    if not markers or markers[0].start() != 0:
        raise Stop("正文須以獨占一行的 §1 開始。")
    if len(markers) > 20:
        raise Stop("一次最多 20 則。")
    posts = []
    for index, marker in enumerate(markers):
        if int(marker.group(1)) != index + 1:
            raise Stop("§ 編號必須由 1 連續遞增。")
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        body = text[marker.end():end].strip()
        # Conservative local limit, not a claim about Meta's character counting.
        units = len(body.encode("utf-16-le")) // 2
        if not body or units > 400 or "§" in body or "\\n" in body:
            raise Stop(f"第 {index + 1} 則為空、超過保守上限 400、或分隔格式錯誤。")
        posts.append(body)
    return posts


class App:
    def __init__(self):
        self.db = str(uuid.UUID(env("NOTION_PERSONAL_DATABASE_ID")))
        self.nh = {"Authorization": "Bearer " + env("NOTION_TOKEN_2"),
                   "Notion-Version": "2025-09-03", "Content-Type": "application/json"}
        self.th = {"Authorization": "Bearer " + env("THREADS_ACCESS_TOKEN"),
                   "Content-Type": "application/json"}
        self.user = env("THREADS_USER_ID")

    def notion(self, method, path, payload=None):
        return http(method, "https://api.notion.com/v1/" + path, self.nh, payload)

    def threads(self, method, path, payload=None):
        return http(method, "https://graph.threads.net/v1.0/" + path, self.th, payload)

    def setup(self):
        db = self.notion("GET", "databases/" + self.db)
        sources = db.get("data_sources", [])
        if len(sources) != 1:
            raise Stop("資料庫必須只有一個資料來源；請先確認設定，不能猜選。")
        self.source = sources[0]["id"]
        schema = self.notion("GET", "data_sources/" + self.source)["properties"]
        for name, kind in [(CONTENT, "rich_text"), (JOURNAL, "rich_text"), ("狀態", "status")]:
            if schema.get(name, {}).get("type") != kind:
                raise Stop(f"Notion 缺少欄位或類型不符：{name} / {kind}")
        names = {v["name"] for v in schema["狀態"]["status"]["options"]}
        if not {READY, BUSY, DONE} <= names:
            raise Stop("狀態選項必須有：新程式待發、發布中、已發。")
        me = self.threads("GET", "me?fields=id,username")
        if str(me.get("id")) != self.user:
            raise Stop("Threads Token 的帳號與 THREADS_USER_ID 不一致。")
        print("目標 Threads 帳號：@" + me.get("username", "unknown"))

    def query(self, status):
        return self.notion("POST", "data_sources/" + self.source + "/query", {
            "filter": {"property": "狀態", "status": {"equals": status}},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            "page_size": 1,
        }).get("results", [])

    def page(self, page_id):
        return self.notion("GET", "pages/" + page_id)

    def text(self, page, name):
        prop = page["properties"][name]
        prop_id = parse.quote(parse.unquote(prop["id"]), safe="")
        base = f"pages/{page['id']}/properties/{prop_id}"
        cursor = None
        fragments = []
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            result = self.notion("GET", base + "?" + parse.urlencode(params))
            for item in result.get("results", []):
                rich = item.get("rich_text", {})
                if rich.get("type") != "text":
                    raise Stop(f"{name} 只接受純文字，不接受提及或公式。")
                fragments.append(rich.get("plain_text", rich.get("text", {}).get("content", "")))
            if not result.get("has_more"):
                return "".join(fragments)
            cursor = result.get("next_cursor")
            if not cursor:
                raise Stop("Notion 分頁回應缺少游標。")

    def save(self, page_id, journal, status=BUSY):
        journal["updated_at"] = datetime.now(timezone.utc).isoformat()
        raw = json.dumps(journal, ensure_ascii=False)
        chunks = [raw[i:i + 1500] for i in range(0, len(raw), 1500)]
        self.notion("PATCH", "pages/" + page_id, {"properties": {
            "狀態": {"status": {"name": status}},
            JOURNAL: {"rich_text": [{"type": "text", "text": {"content": c}} for c in chunks]},
        }})

    def guard(self, page_id, original, run_id=None):
        page = self.page(page_id)
        if page.get("archived") or page.get("in_trash"):
            raise Stop("Notion 頁面已移除。")
        expected = BUSY if run_id else READY
        actual = (page["properties"]["狀態"].get("status") or {}).get("name")
        if actual != expected or self.text(page, CONTENT) != original:
            raise Stop("正文或狀態已改變，停止發布。")
        raw = self.text(page, JOURNAL)
        if run_id:
            try:
                matches = json.loads(raw).get("run_id") == run_id
            except (ValueError, AttributeError):
                matches = False
            if not matches:
                raise Stop("發文紀錄已被其他程序修改。")
        elif raw.strip():
            raise Stop("這筆已有發文紀錄，禁止從頭重發；請先人工核對。")

    def ready_container(self, cid):
        for attempt in range(6):
            if attempt:
                time.sleep(60)
            state = self.threads("GET", cid + "?fields=status").get("status")
            if state == "FINISHED":
                return
            if state != "IN_PROGRESS":
                raise Stop("Container 非可發布狀態，停止並保留紀錄。")
        raise Stop("Container 五分鐘內尚未就緒，請人工確認。")

    def run(self, publish=False):
        self.setup()
        if self.query(BUSY):
            raise Stop("存在『發布中』紀錄。先核對前次執行，禁止盲目重跑。")
        queue = self.query(READY)
        if not queue:
            print("沒有『新程式待發』內容，未發布。")
            return
        page = queue[0]
        pid = page["id"]
        original = self.text(page, CONTENT)
        posts = split_posts(original)
        self.guard(pid, original)
        digest = hashlib.sha256(original.encode()).hexdigest()
        print(f"檢查通過：{len(posts)} 則；正文 SHA256：{digest}")
        print("各則長度：" + ", ".join(str(len(p.encode('utf-16-le')) // 2) for p in posts))
        if not publish:
            print("DRY RUN：未發文、未建 container、未修改 Notion。正文請在 Notion 核對。")
            return
        journal = {"run_id": str(uuid.uuid4()), "sha256": digest,
                   "total": len(posts), "phase": "claimed", "published_ids": []}
        self.save(pid, journal)
        self.guard(pid, original, journal["run_id"])
        for number, body in enumerate(posts, 1):
            self.guard(pid, original, journal["run_id"])
            journal.update(phase="creating", part=number, container_id=None)
            self.save(pid, journal)
            data = {"media_type": "TEXT", "text": body}
            if journal["published_ids"]:
                data["reply_to_id"] = journal["published_ids"][-1]
            cid = self.threads("POST", self.user + "/threads", data).get("id")
            if not cid:
                raise Stop("建立 container 沒有回傳 ID，停止。")
            journal.update(phase="container_created", container_id=cid)
            self.save(pid, journal)
            self.ready_container(cid)
            self.guard(pid, original, journal["run_id"])
            journal["phase"] = "publish_requested"
            self.save(pid, journal)  # Durable intent BEFORE the external side effect.
            result = self.threads("POST", self.user + "/threads_publish", {"creation_id": cid})
            post_id = result.get("id")
            if not post_id:
                raise Stop("發布結果沒有 ID；請核對帳號，不能直接重發。")
            print(f"第 {number} 則已發布，Threads ID：{post_id}")
            journal["published_ids"].append(post_id)
            journal["phase"] = "part_published"
            self.save(pid, journal)
            if number < len(posts):
                time.sleep(10)
        self.guard(pid, original, journal["run_id"])
        journal["phase"] = "complete"
        self.save(pid, journal, DONE)
        print("全部發布完成，Notion 已更新為『已發』。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="實際發文；省略時只檢查")
    args = parser.parse_args()
    try:
        App().run(args.publish)
    except (Stop, ValueError, KeyError) as exc:
        if isinstance(exc, Stop):
            print("停止：" + str(exc), file=sys.stderr)
        else:
            print("停止：設定或 API 資料格式不符。", file=sys.stderr)
        print("若已有『發布中』紀錄，保留它並核對 Threads／Actions；不要清空後重發。", file=sys.stderr)
        sys.exit(1)
