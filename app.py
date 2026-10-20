"""数据管理库 — Python standard library only."""
import argparse
from contextlib import contextmanager
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import uuid
import zipfile
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_LIBRARY_HOME", ROOT / "data"))
MAX_FILE = 50 * 1024 * 1024


@contextmanager
def connect():
    db = sqlite3.connect(DATA / "library.sqlite")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def init():
    (DATA / "files").mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS folders(
          id TEXT PRIMARY KEY, name TEXT NOT NULL,
          parent TEXT REFERENCES folders(id));
        CREATE TABLE IF NOT EXISTS files(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, folder TEXT REFERENCES folders(id),
          size INTEGER NOT NULL, tags TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now')));
        """)


def preview(path, name):
    ext = Path(name).suffix.lower()
    if ext == ".pptx":
        with zipfile.ZipFile(path) as z:
            slides = sorted((n for n in z.namelist() if
                             __import__("re").fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                            key=lambda n: int(__import__("re").search(r"slide(\d+)", n).group(1)))
            result = []
            total = 0
            for n in slides[:100]:
                size = z.getinfo(n).file_size
                total += size
                if total > 8 * 1024 * 1024:
                    raise ValueError("PPT 解压内容过大，无法预览")
                root = ET.fromstring(z.read(n))
                result.append("\n".join(t.text or "" for t in root.iter()
                                        if t.tag.endswith("}t")))
            return {"kind": "slides", "slides": result, "total": len(slides)}
    if ext in (".csv", ".tsv", ".txt", ".md", ".json"):
        with path.open("rb") as source:
            raw = source.read(256 * 1024)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", errors="replace")
        if ext in (".csv", ".tsv"):
            rows = []
            for row in csv.reader(io.StringIO(text), delimiter="\t" if ext == ".tsv" else ","):
                rows.append(row[:40])
                if len(rows) == 100:
                    break
            return {"kind": "table", "rows": rows}
        return {"kind": "text", "text": text[:30000]}
    return {"kind": "download"}


class Handler(BaseHTTPRequestHandler):
    def send(self, status, payload, content_type="application/json; charset=utf-8", extra=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self.get()
        except (ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as e:
            self.send(400, {"error": str(e)})
        except Exception:
            self.send(500, {"error": "读取失败，请检查本地文件是否完整"})

    def get(self):
        url = urlparse(self.path)
        if url.path == "/api/library":
            with connect() as db:
                self.send(200, {"folders": [dict(r) for r in db.execute("SELECT * FROM folders ORDER BY name")],
                                "files": [dict(r) for r in db.execute("SELECT * FROM files ORDER BY created DESC")]})
            return
        if url.path.startswith("/api/file/"):
            fid = url.path.split("/")[-1]
            with connect() as db:
                f = db.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
            if not f:
                self.send(404, {"error": "文件不存在"})
                return
            path = DATA / "files" / fid
            if "preview" in parse_qs(url.query):
                self.send(200, preview(path, f["name"]))
                return
            ext = Path(f["name"]).suffix.lower()
            types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".webp": "image/webp"}
            inline = ext in types and "download" not in parse_qs(url.query)
            self.send(200, path.read_bytes(), types[ext] if inline else "application/octet-stream",
                      {"Content-Disposition": ("inline" if inline else "attachment") +
                       "; filename*=UTF-8''" + quote(f["name"])})
            return
        static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        if url.path in static:
            name = static[url.path]
            mime = {"html": "text/html", "js": "text/javascript", "css": "text/css"}[name.split(".")[-1]]
            self.send(200, (ROOT / "web" / name).read_bytes(), mime + "; charset=utf-8")
        else:
            self.send(404, {"error": "页面不存在"})

    def do_POST(self):
        # Same-origin mutation guard; reject browser requests from other sites.
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self.send(403, {"error": "不允许跨站写入"})
            return
        if self.headers.get("X-Library-Request") != "1":
            self.send(403, {"error": "缺少请求标记"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0 or size > MAX_FILE:
                self.send(413, {"error": "单个文件不能超过 50 MB"})
                return
            url = urlparse(self.path)
            body = self.rfile.read(size)
            if url.path == "/api/upload":
                q = parse_qs(url.query)
                name = q.get("name", [""])[0].replace("\\", "/").split("/")[-1].strip()
                if not name or len(name) > 255:
                    raise ValueError("文件名无效")
                folder = q.get("folder", [None])[0] or None
                fid = uuid.uuid4().hex
                path = DATA / "files" / fid
                try:
                    with connect() as db:
                        db.execute("INSERT INTO files(id,name,folder,size) VALUES(?,?,?,?)", (fid, name, folder, size))
                        path.write_bytes(body)
                except Exception:
                    path.unlink(missing_ok=True)
                    raise
                self.send(201, {"id": fid})
                return
            obj = json.loads(body)
            with connect() as db:
                if url.path == "/api/folder":
                    name = str(obj.get("name", "")).strip()
                    if not name or len(name) > 100:
                        raise ValueError("目录名称须为 1–100 个字符")
                    db.execute("INSERT INTO folders VALUES(?,?,?)", (uuid.uuid4().hex, name, obj.get("parent") or None))
                elif url.path == "/api/update":
                    f = db.execute("SELECT * FROM files WHERE id=?", (obj["id"],)).fetchone()
                    if not f:
                        raise ValueError("文件不存在")
                    db.execute("UPDATE files SET folder=?, tags=? WHERE id=?",
                               (obj.get("folder") or None, str(obj.get("tags", ""))[:500], obj["id"]))
                elif url.path == "/api/delete":
                    f = db.execute("SELECT id FROM files WHERE id=?", (obj["id"],)).fetchone()
                    if not f:
                        raise ValueError("文件不存在")
                    db.execute("DELETE FROM files WHERE id=?", (f["id"],))
                elif url.path == "/api/delete-folder":
                    db.execute("DELETE FROM folders WHERE id=?", (obj["id"],))
                else:
                    self.send(404, {"error": "接口不存在"})
                    return
            if url.path == "/api/delete":
                (DATA / "files" / f["id"]).unlink(missing_ok=True)
            self.send(200, {"ok": True})
        except sqlite3.IntegrityError:
            self.send(400, {"error": "目录不存在，或目录中仍有文件/子目录"})
        except (ValueError, KeyError):
            self.send(400, {"error": "请求内容无效，请检查名称或所选目录"})
        except Exception:
            self.send(500, {"error": "保存失败，请检查磁盘空间和目录权限"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    init()
    print(f"数据管理库 http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
