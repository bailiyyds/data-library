import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import zipfile

spec = importlib.util.spec_from_file_location("library", Path(__file__).resolve().parents[1] / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        app.DATA = Path(cls.tmp.name)
        app.init()
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def request(self, path, body=None, headers=None):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        r = urllib.request.Request(self.url + path, data=body,
                                   headers=headers if headers is not None else {"X-Library-Request": "1"})
        with urllib.request.urlopen(r) as response:
            return json.loads(response.read())

    def test_full_lifecycle(self):
        self.request("/api/folder", {"name": "项目"})
        state = self.request("/api/library")
        parent = state["folders"][0]["id"]
        self.request("/api/folder", {"name": "数据", "parent": parent})
        child = next(f["id"] for f in self.request("/api/library")["folders"] if f["parent"])
        fid = self.request("/api/upload?name=example.csv&folder="+child, b"name,value\nA,42")["id"]
        self.assertEqual(self.request("/api/file/"+fid+"?preview=1")["rows"][1], ["A", "42"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/delete-folder", {"id": parent})
        self.assertEqual(error.exception.code, 400)
        self.request("/api/update", {"id": fid, "folder": parent, "tags": "结果"})
        app.init()
        self.assertEqual(self.request("/api/library")["files"][0]["tags"], "结果")
        with urllib.request.urlopen(self.url+"/api/file/"+fid+"?download=1") as r:
            self.assertEqual(r.read(), b"name,value\nA,42")
        self.request("/api/delete", {"id": fid})
        self.assertFalse((app.DATA / "files" / fid).exists())
        self.request("/api/delete-folder", {"id": child})
        self.request("/api/delete-folder", {"id": parent})

    def test_mutation_guard(self):
        for headers in ({}, {"X-Library-Request": "1", "Origin": "https://other.example"}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/folder", {"name": "bad"}, headers)
            self.assertEqual(error.exception.code, 403)

    def test_pptx_and_invalid_folder(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("ppt/slides/slide1.xml", '<p xmlns:a="urn:test"><a:t>Hello slides</a:t></p>')
        fid = self.request("/api/upload?name=slides.pptx", buf.getvalue())["id"]
        self.assertEqual(self.request("/api/file/"+fid+"?preview=1")["slides"], ["Hello slides"])
        self.request("/api/delete", {"id": fid})
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/api/upload?name=x.csv&folder=missing", b"abc")
        self.assertEqual(list((app.DATA / "files").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
