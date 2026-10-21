"""User-only publication with durable receipts; no OAuth token storage here."""
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid

VERSION = "0.2.0"
BASE_SCOPES = ["auth:user.id:read", "offline_access", "docx:document"]
API_BASES = {"https://open.feishu.cn": "https://www.feishu.cn",
             "https://open.larksuite.com": "https://www.larksuite.com"}
MAX_INPUT_BYTES = 20 * 1024 * 1024


class PublishError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def safe_text(value, token=""):
    value = str(value)
    if token:
        value = value.replace(token, "[redacted]")
    value = re.sub(r'(?i)(Bearer\s+)\S+', r'\1[redacted]', value)
    value = re.sub(r'(?i)((?:access_token|refresh_token|app_secret)["\s:=]+)[^\s,}\"]+',
                   r'\1[redacted]', value)
    return value[:2000]


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PublishError(f"状态目录须由当前用户拥有且权限为 0700：{path}")


def write_json(path, value):
    private_dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path):
    try:
        info = path.lstat()
        if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PublishError(f"状态文件须由当前用户拥有且权限为 0600：{path}")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublishError(f"无法读取状态文件 {path.name}：{type(exc).__name__}") from None


@contextlib.contextmanager
def lock(root, key):
    private_dir(root)
    fd = os.open(root / (key + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PublishError("同一发布请求正在执行；请查看原请求结果，未重复提交。") from None
        yield
    finally:
        os.close(fd)


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("FEISHU_")}
    env.update(FEISHU_DEBUG="false", FEISHU_TRANSFER_OWNERSHIP="false", FEISHU_OWNER_EMAIL="")
    return env


class CLI:
    def __init__(self, profile, binary="feishu-cli"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
            raise PublishError("profile 只能使用字母、数字、下划线和连字符。")
        self.profile = profile
        self.binary = shutil.which(binary)
        if not self.binary:
            raise PublishError("找不到 feishu-cli；请安装 v1.43.0 或指定 --cli。")
        self.config = Path.home() / ".feishu-cli/profiles" / profile / "config.yaml"
        if not self.config.is_file():
            raise PublishError(f"profile 尚未配置：先运行 feishu-cli --profile {profile} config create-app --save")

    def command(self, args):
        return [self.binary, "--profile", self.profile, "--config", str(self.config), *args]

    def run(self, args, token="", timeout=60):
        env = clean_env()
        if token:
            env["FEISHU_USER_ACCESS_TOKEN"] = token
        try:
            return subprocess.run(self.command(args), env=env, capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise PublishError("上游命令超时；写入可能已发生，未自动重试。") from None

    def value(self, key):
        result = self.run(["config", "get", key])
        if result.returncode:
            raise PublishError(f"无法读取 CLI 配置项 {key}：{safe_text(result.stderr)}")
        return result.stdout.strip()

    def user_token(self):
        # stdout is captured only in memory, never logged or placed in argv.
        result = self.run(["auth", "token", "--as", "user"])
        token = result.stdout.strip()
        if result.returncode or not token or any(c.isspace() for c in token):
            raise PublishError(f"用户授权不可用（退出码 {result.returncode}）；请运行 feishu-publish login。"
                               f" {safe_text(result.stderr)}")
        return token

    def login(self, scopes):
        if self.value("base_url").rstrip("/") not in API_BASES:
            raise PublishError("用户授权仅接受官方飞书/Lark API 地址。")
        # Human-mode upstream login prints an authorization URL, not tokens.
        return subprocess.call(self.command(["auth", "login", "--scope", " ".join(scopes)]), env=clean_env())

    def import_markdown(self, path, document_id, token):
        result = self.run(["doc", "import", str(path), "--document-id", document_id,
                           "--diagram-retries", "0", "-o", "json"], token=token, timeout=600)
        try:
            report = json.loads(result.stdout)
        except ValueError:
            raise PublishError(f"导入未返回可核验 JSON（退出码 {result.returncode}）；保留原文档。"
                               f" {safe_text(result.stderr, token)}") from None
        if not isinstance(report, dict) or report.get("document_id") != document_id:
            raise PublishError("导入返回的文档编号与已创建文档不一致。")
        # Keep diagnostics without copying source content, URLs or raw errors into receipts.
        summary = {k: v for k, v in report.items()
                   if isinstance(v, (int, float, bool)) and k not in {"duration_seconds"}}
        summary["exit_code"] = result.returncode
        summary["failure_count"] = len(report.get("failures") or [])
        summary["ok"] = (result.returncode == 0 and report.get("partial_failure") is False
                         and summary["failure_count"] == 0
                         and not any(v for k, v in summary.items() if k.endswith("_failed") or k.endswith("_skipped")))
        return summary


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, base, token):
        if base not in API_BASES or not token:
            raise PublishError("仅接受官方飞书/Lark API 地址及有效用户令牌。")
        self.base, self.token = base, token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, body=None, content_type="application/json"):
        if not path.startswith("/open-apis/"):
            raise PublishError("无效 API 路径。")
        data = body if isinstance(body, bytes) else (encoded(body) if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": content_type})
        try:
            with self.opener.open(req, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                problem = json.loads(exc.read())
            except (ValueError, OSError):
                problem = {}
            finally:
                exc.close()
            if not isinstance(problem, dict):
                problem = {}
            raise PublishError(f"飞书 HTTP {exc.code}，code={problem.get('code', 'unknown')}，"
                               f"{safe_text(problem.get('msg', '请求失败'), self.token)}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise PublishError(f"飞书响应未确认（{type(exc).__name__}）；未自动重试。") from None
        if not isinstance(result, dict) or result.get("code") != 0:
            raise PublishError(f"飞书 API 失败：{safe_text(result, self.token)}")
        data = result.get("data")
        if not isinstance(data, dict):
            raise PublishError("飞书响应缺少 data 对象。")
        return data

    def upload_word(self, path, data):
        boundary = "feishupublish" + uuid.uuid4().hex
        fields = {"file_name": path.name, "parent_type": "ccm_import_open", "size": str(len(data)),
                  "extra": json.dumps({"obj_type": "docx", "file_extension": path.suffix[1:].lower()})}
        parts = []
        for key, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        # Constant multipart filename avoids header injection from a local filename.
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="document{path.suffix.lower()}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        parts.extend([data, f'\r\n--{boundary}--\r\n'.encode()])
        return self.request("POST", "/open-apis/drive/v1/medias/upload_all", b"".join(parts),
                            "multipart/form-data; boundary=" + boundary)["file_token"]


def connect(cli):
    base, app = cli.value("base_url").rstrip("/"), cli.value("app_id")
    if base not in API_BASES or not app:
        raise PublishError("无法确认官方 API 地址和应用编号；未请求用户令牌。")
    token = cli.user_token()
    api = API(base, token)
    user = api.request("GET", "/open-apis/authen/v1/user_info")
    if not app or not user.get("open_id"):
        raise PublishError("无法确认当前应用及授权用户；未创建文档。")
    identity = {"kind": "user", "app_id": app, "open_id": user["open_id"],
                "tenant_key": user.get("tenant_key", ""), "api_base": base}
    return api, identity


def checked_file(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise PublishError("输入须为不超过 20 MiB 的普通文件。")
    if any(part in {".ssh", ".aws", ".feishu-cli", ".gnupg"} for part in path.parts) or str(path).startswith("/etc/"):
        raise PublishError("拒绝上传凭据或系统配置目录中的文件。")
    return path, path.read_bytes()


def prepare(path, assets=()):
    path, data = checked_file(path)
    kind = path.suffix.lower()
    if kind not in {".md", ".markdown", ".txt", ".docx", ".doc"}:
        raise PublishError("支持 .md、.markdown、.txt、.docx 和 .doc。")
    text = None
    if kind in {".md", ".markdown", ".txt"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise PublishError("文本输入必须使用 UTF-8 编码。") from None
        if not text.strip() or "\ufffd" in text:
            raise PublishError("正文为空或含 Unicode 替换字符；请先修正输入。")
    manifest = []
    for asset in assets:
        item, content = checked_file(asset)
        manifest.append({"path": str(item), "sha256": digest(content)})
    fingerprint = digest(encoded({"source": digest(data), "format": kind,
                                  "assets": sorted(manifest, key=lambda x: x["path"])}))
    return {"path": path, "data": data, "text": text, "kind": kind,
            "sha256": fingerprint, "source_sha256": digest(data), "assets": manifest}


def folder_token(value):
    if not value:
        return ""
    if "://" in value:
        url = urllib.parse.urlparse(value)
        if url.scheme != "https" or not url.hostname or not any(
            url.hostname == domain or url.hostname.endswith("." + domain)
            for domain in ("feishu.cn", "larksuite.com")
        ) or url.username:
            raise PublishError("文件夹链接须为飞书/Lark HTTPS 链接。")
        match = re.fullmatch(r"/drive/(?:folder|shr)/([A-Za-z0-9]+)/?", url.path)
        if not match:
            raise PublishError("目标须为云盘文件夹，不接受知识库文档节点。")
        value = match[1]
    if not re.fullmatch(r"[A-Za-z0-9]+", value):
        raise PublishError("文件夹 token 格式不正确。")
    return value


def normalized(text):
    return "".join(unicodedata.normalize("NFC", text).split())


class Publisher:
    def __init__(self, root, cli, api, identity):
        self.root, self.cli, self.api, self.identity = Path(root), cli, api, identity

    def save(self, record):
        record["updated_at"] = now()
        write_json(self.root / (record["key"] + ".json"), record)

    def checkpoint(self, record, state):
        record["state"] = state
        record.setdefault("events", []).append({"at": now(), "state": state})
        self.save(record)

    def readback(self, record):
        doc = record["document_id"]
        prefix = "/open-apis/docx/v1/documents/" + urllib.parse.quote(doc, safe="")
        metadata = self.api.request("GET", prefix).get("document", {})
        content = self.api.request("GET", prefix + "/raw_content").get("content")
        if not isinstance(content, str):
            raise PublishError("正文回读缺少 content。")
        missing = [item for item in record.get("expect_text", []) if normalized(item) not in normalized(content)]
        expected_plain = record.get("plain_text_sha256")
        # Plain text is checked in full, after removing the document-title prefix.
        body = content
        if body == record["title"]:
            body = ""
        elif body.startswith(record["title"] + "\n"):
            body = body[len(record["title"]) + 1:]
        plain_matches = digest(normalized(body).encode()) == expected_plain if expected_plain else None
        result = {"api_readable": True, "raw_chars": len(content), "raw_sha256": digest(content.encode()),
                  "revision_id": metadata.get("revision_id"), "title_matches": metadata.get("title") == record["title"],
                  "expected_text_checks": len(record.get("expect_text", [])), "missing_text_checks": len(missing),
                  "plain_text_matches": plain_matches, "full_rich_content_verified": False,
                  "visual_review_required": record["format"] != ".txt", "checked_at": now()}
        result["ok"] = bool(body.strip()) and result["title_matches"] and not missing and plain_matches is not False
        record["readback"] = result
        return result

    def verify(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise PublishError("无效的发布记录编号。")
        with lock(self.root, key):
            record = read_json(self.root / (key + ".json"))
            if record["identity"] != self.identity:
                raise PublishError("当前授权用户与原发布记录不一致；未访问原文档。")
            try:
                if record.get("ticket") and not record.get("document_id"):
                    self.poll_word(record)
                if not record.get("document_id"):
                    raise PublishError("创建结果尚不明确且没有文档编号；请先核查云盘，不能自动重建。")
                self.readback(record)
                if record.get("import", {}).get("ok") and record["readback"]["ok"]:
                    record.pop("error", None)
                    self.checkpoint(record, "published")
                else:
                    self.checkpoint(record, "needs_review")
            except (PublishError, OSError, KeyError, TypeError) as exc:
                self.failure(record, exc)
                self.checkpoint(record, "readback_failed")
            return self.result(record, reused=True)

    def poll_word(self, record):
        # Only polls a saved ticket; never replays creation or upload.
        for _ in range(30):
            result = self.api.request("GET", "/open-apis/drive/v1/import_tasks/" +
                                      urllib.parse.quote(record["ticket"], safe=""))["result"]
            status = result.get("job_status")
            if status == 0 and result.get("token"):
                record["document_id"] = result["token"]
                record["url"] = API_BASES[self.api.base] + "/docx/" + result["token"]
                record["import"] = {"ok": True, "method": "word_import"}
                self.checkpoint(record, "imported")
                return
            if status not in (1, 2):
                raise PublishError(f"Word 导入失败：job_status={status}；保留原 ticket。")
            time.sleep(1)
        raise PublishError("Word 导入仍在处理中；使用 verify 查询原 ticket，不要重新上传。")

    def publish(self, source, title=None, folder="", expected=(), copy_key=""):
        title = (title or source["path"].stem).strip()
        if not title or len(title) > 800 or any(ord(c) < 32 for c in title):
            raise PublishError("标题须为非空单行文字（最多 800 字符）。")
        folder = folder_token(folder)
        spec = {"identity": self.identity, "input_sha256": source["sha256"], "title": title,
                "folder": folder, "format": source["kind"], "copy_key": copy_key}
        key = digest(encoded(spec))
        with lock(self.root, key):
            path = self.root / (key + ".json")
            if path.exists():
                record = read_json(path)
                # Existing results are returned without a second mutation. Recheck only safe reads.
                try:
                    if record.get("import", {}).get("ok") and record.get("document_id"):
                        record["expect_text"] = list(dict.fromkeys(record.get("expect_text", []) + list(expected)))
                        self.readback(record)
                        record.pop("error", None)
                        self.checkpoint(record, "published" if record["readback"]["ok"] else "needs_review")
                except PublishError as exc:
                    self.failure(record, exc)
                    self.checkpoint(record, "readback_failed")
                return self.result(record, reused=True)
            record = {**spec, "schema": 1, "key": key, "created_at": now(), "profile": self.cli.profile,
                      "source_sha256": source["source_sha256"], "assets": source["assets"],
                      "expect_text": list(expected), "state": "prepared"}
            if source["kind"] == ".txt":
                record["plain_text_sha256"] = digest(normalized(source["text"]).encode())
            self.checkpoint(record, "prepared")
            try:
                if source["kind"] in {".docx", ".doc"}:
                    self.checkpoint(record, "upload_pending")
                    file_token = self.api.upload_word(source["path"], source["data"])
                    record["file_token"] = file_token
                    self.checkpoint(record, "import_task_pending")
                    response = self.api.request("POST", "/open-apis/drive/v1/import_tasks", {
                        "file_extension": source["kind"][1:], "file_token": file_token,
                        "type": "docx", "file_name": title, "point": {"mount_type": 1, "mount_key": folder}})
                    record["ticket"] = response["ticket"]
                    self.checkpoint(record, "import_task_started")
                    self.poll_word(record)
                else:
                    self.checkpoint(record, "create_pending")
                    payload = {"title": title}
                    if folder:
                        payload["folder_token"] = folder
                    response = self.api.request("POST", "/open-apis/docx/v1/documents", payload)
                    record["document_id"] = response["document"]["document_id"]
                    record["url"] = API_BASES[self.api.base] + "/docx/" + record["document_id"]
                    self.checkpoint(record, "created")
                    self.checkpoint(record, "content_pending")
                    if source["kind"] == ".txt":
                        self.write_plain(record, source["text"])
                        record["import"] = {"ok": True, "method": "plain_blocks"}
                    else:
                        record["import"] = self.cli.import_markdown(source["path"], record["document_id"], self.api.token)
                    # A changing source or declared asset invalidates this publication's input identity.
                    after = prepare(source["path"], [item["path"] for item in source["assets"]])
                    if after["sha256"] != source["sha256"]:
                        record["import"]["ok"] = False
                        record["error"] = "发布期间输入或已声明素材发生变化，需核对现有文档。"
                    self.checkpoint(record, "imported" if record["import"]["ok"] else "partial")
                self.readback(record)
                self.checkpoint(record, "published" if record["import"]["ok"] and record["readback"]["ok"] else "needs_review")
            except (PublishError, OSError, KeyError, TypeError) as exc:
                self.failure(record, exc)
            return self.result(record)

    def failure(self, record, exc):
        record["error"] = safe_text(exc, self.api.token)
        record["failed_at"] = now()
        record.setdefault("failures", []).append({"at": now(), "stage": record["state"], "error": record["error"]})
        self.save(record)

    def write_plain(self, record, text):
        blocks = []
        for line in text.splitlines():
            for offset in range(0, max(len(line), 1), 1000):
                blocks.append({"block_type": 2, "text": {"elements": [
                    {"text_run": {"content": line[offset:offset + 1000]}}]}})
        doc = record["document_id"]
        for start in range(0, len(blocks), 50):
            self.api.request("POST", f"/open-apis/docx/v1/documents/{doc}/blocks/{doc}/children",
                             {"children": blocks[start:start + 50], "index": -1})
            record["plain_blocks_written"] = start + len(blocks[start:start + 50])
            self.save(record)

    @staticmethod
    def result(record, reused=False):
        return {"ok": record["state"] == "published", "key": record["key"], "state": record["state"],
                "reused": reused, "identity": "user", "url": record.get("url"),
                "document_id": record.get("document_id"), "readback": record.get("readback"),
                "import": record.get("import"), "error": record.get("error"),
                "next_step": None if record["state"] == "published" else
                "保留原结果；使用 verify <key> 只读核查。结果不明确时先核查云盘，不重复创建。"}
