import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


PORT = int(os.environ.get("PORT", "8080"))
ISSUER_BASE_URL = os.environ.get("ISSUER_BASE_URL", f"http://127.0.0.1:{PORT}")
REALM_PATH = "/realms/detection-center"
DISCOVERY_PATH = f"{REALM_PATH}/.well-known/openid-configuration"
JWKS_PATH = f"{REALM_PATH}/protocol/openid-connect/certs"

HERE = Path(__file__).resolve().parent
JWKS = json.loads((HERE / "jwks.json").read_text(encoding="utf-8"))

DISCOVERY = {
    "issuer": f"{ISSUER_BASE_URL}{REALM_PATH}",
    "jwks_uri": f"{ISSUER_BASE_URL}{JWKS_PATH}",
    "authorization_endpoint": f"{ISSUER_BASE_URL}{REALM_PATH}/protocol/openid-connect/auth",
    "token_endpoint": f"{ISSUER_BASE_URL}{REALM_PATH}/protocol/openid-connect/token",
    "userinfo_endpoint": f"{ISSUER_BASE_URL}{REALM_PATH}/protocol/openid-connect/userinfo",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
}


class Handler(BaseHTTPRequestHandler):
    server_version = "i4-oidc-stub/1.0"

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == DISCOVERY_PATH:
            self._json(200, DISCOVERY)
            return
        if self.path == JWKS_PATH:
            self._json(200, JWKS)
            return
        self._json(404, {"detail": "not_found"})


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
