"""Generate a high-entropy access key and its AUTH_ACCOUNTS entry locally."""

import argparse
import hashlib
import json
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--role", choices=["reader", "reviewer"], default="reader")
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    print("Access key (give this to the named user; store securely):")
    print(token)
    print("Account entry (merge into the AUTH_ACCOUNTS JSON array in .env):")
    print(
        json.dumps(
            {
                "user_id": args.user,
                "tenant_id": args.tenant,
                "role": args.role,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
