#!/usr/bin/env python3
"""
Serve the map layout editor and accept saves. Stdlib only.

    python serve_editor.py            # http://localhost:8081/map_editor.html

Serves the repo root (so the editor can fetch map_layout.json,
output/data.json, and assets/*), plus two endpoints:

  POST /api/save    body = the full map_layout.json document.
                    Validates top-level keys, backs up the current file to
                    map_layout.json.bak, then writes atomically.
  POST /api/render  body = {"plain": bool, "label": str|null}
                    Runs build_print_map.py synchronously and returns its
                    output, so the editor's "Render" button can produce a
                    real poster preview (output/print/preview*.png).
"""

import json
import shutil
import subprocess
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
LAYOUT_PATH = ROOT / "map_layout.json"
PORT = 8081

REQUIRED_KEYS = {
    "label_style", "display_names", "stop_overrides", "mountains",
    "conifers", "broadleaf", "lakes", "parks", "waypoints",
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json_response(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self):
        try:
            if self.path == "/api/save":
                self._handle_save()
            elif self.path == "/api/render":
                self._handle_render()
            else:
                self._json_response(404, {"ok": False, "error": "unknown endpoint"})
        except Exception as e:  # surface the reason to the UI
            self._json_response(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def _handle_save(self):
        layout = self._read_body()
        missing = REQUIRED_KEYS - set(layout)
        if missing:
            self._json_response(400, {"ok": False,
                                      "error": f"missing keys: {sorted(missing)}"})
            return
        if LAYOUT_PATH.exists():
            shutil.copy2(LAYOUT_PATH, LAYOUT_PATH.with_suffix(".json.bak"))
        tmp = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(ROOT), suffix=".tmp", delete=False)
        with tmp as f:
            json.dump(layout, f, indent=2, ensure_ascii=False)
        Path(tmp.name).replace(LAYOUT_PATH)
        self._json_response(200, {"ok": True})

    def _handle_render(self):
        opts = self._read_body()
        cmd = [sys.executable, str(ROOT / "build_print_map.py")]
        if opts.get("plain"):
            cmd.append("--plain")
        label = opts.get("label")
        if label:
            cmd += ["--label", str(label)]
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                              text=True, timeout=300)
        self._json_response(200 if proc.returncode == 0 else 500, {
            "ok": proc.returncode == 0,
            "output": (proc.stdout + proc.stderr)[-2000:],
        })

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Map editor: http://localhost:{PORT}/map_editor.html  (Ctrl+C to stop)")
    server.serve_forever()
