import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt


HERE = Path(__file__).resolve().parent
PRIVATE_KEY = (HERE / "private_key.pem").read_text(encoding="utf-8")
KID = "i4-oidc-test-key"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issuer-base-url", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--center-id", required=True)
    parser.add_argument("--role", action="append", dest="roles", required=True)
    parser.add_argument("--name", default="I4 Scheduler")
    parser.add_argument("--client-id", default="detection-center-web")
    parser.add_argument("--ttl-minutes", type=int, default=30)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    issuer = args.issuer_base_url.rstrip("/") + "/realms/detection-center"
    payload = {
        "iss": issuer,
        "sub": args.subject,
        "aud": args.client_id,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=args.ttl_minutes)).timestamp()),
        "name": args.name,
        "center_id": args.center_id,
        "roles": args.roles,
    }
    token = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})
    print(token)


if __name__ == "__main__":
    main()
