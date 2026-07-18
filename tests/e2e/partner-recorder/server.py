import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


STORE_FILE = os.environ.get("STORE_FILE", "/data/requests.jsonl")
PORT = int(os.environ.get("PORT", "8080"))


def append_record(record: dict) -> None:
    os.makedirs(os.path.dirname(STORE_FILE), exist_ok=True)
    with open(STORE_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_records() -> list[dict]:
    if not os.path.exists(STORE_FILE):
        return []
    records: list[dict] = []
    with open(STORE_FILE, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


class Handler(BaseHTTPRequestHandler):
    server_version = "partner-recorder/1.0"

    def _json(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return ""
        return self.rfile.read(length).decode("utf-8")

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/requests":
            self._json(200, {"requests": load_records()})
            return
        self._json(404, {"detail": "not_found"})

    def do_OPTIONS(self) -> None:
        if self.path.startswith("/internal/v1/centers/"):
            self.send_response(204)
            self.send_header("Allow", "OPTIONS, PUT")
            self.end_headers()
            return
        if self.path == "/notification-webhook":
            self.send_response(204)
            self.send_header("Allow", "OPTIONS, POST")
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()

    def do_PUT(self) -> None:
        body = self._read_body()
        append_record(
            {
                "method": "PUT",
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:
        body = self._read_body()
        append_record(
            {
                "method": "POST",
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.send_response(202)
        self.end_headers()


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
