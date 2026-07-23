# Production secret files

Create this directory outside the repository at the `SECRETS_DIR` declared in
the production Compose environment file. Each file is root-owned, mode `0400`,
contains one value with no surrounding quotes, and is mounted read-only by
Docker Compose. Do not commit the files or copy their contents to an env file.

Required filenames:

- `postgres_password`
- `rabbitmq_default_password`
- `redis_password`
- `api_database_url`
- `api_rabbitmq_url`
- `api_redis_url`
- `internal_service_token`
- `oidc_client_secret`
- `partner_schedule_credential`
- `notification_webhook_credential`
- `scheduler_service_bearer_token`
- `scheduler_callback_service_token`

The Go API service `*_FILE` configuration is an I7 runtime contract: it reads
the named file at startup and must not log its value. The existing Python
services receive the same secret files through their deployment entrypoints,
which export values only to their child process and never write a secret to
Compose, logs, or a tracked file. `internal_service_token` is the shared
Go-to-AI bearer value required by the existing internal API contract. The URL
files use private Docker hostnames (`postgres`, `rabbitmq`, `redis`) and the
password files above; no value may use `guest`, `localhost`, `ops-stub`, or a
known placeholder.
