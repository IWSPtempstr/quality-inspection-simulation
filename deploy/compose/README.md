# Deployment Compose Files

`compose.yaml` remains the development and controlled E2E base. It contains
the deliberately non-production `ops-stub` and optional host ports. Do not use
it on a server. Production is the standalone
`deploy/compose/compose.prod.yaml`; it has no dependency on the development
file and exposes only the Nginx edge on ports 80 and 443.

## Required operations input

Production launch is blocked until operations provides all of the following:

- a DNS name resolving to the server and an ACME contact email;
- an enterprise OIDC issuer or Keycloak realm, registered redirect URI
  `https://<hostname>/api/v1/auth/callback`, and the verified center/role claim
  mapping (`admin`, `scheduler`, `operator`, `viewer`);
- an HTTPS partner write-back endpoint and credential;
- an HTTPS notification channel or controlled production adapter and credential;
- root-owned secret files, firewall rules allowing only 80/443 and private
  administrative access, an off-server backup destination, and a named
  rollback owner.

The server needs Docker Engine with the Compose plugin, `openssl` for the
initial ACME bootstrap, and sufficient persistent disk. RabbitMQ management is
not published; access it only through approved VPN or SSH forwarding.

## Server preparation

1. Create `/srv/detection-center/{data,certificates,acme-webroot,secrets}`.
   Create data subdirectories `postgres`, `rabbitmq`, `redis`, `chroma`,
   `postgres-backups`, and `chroma-backups`. Assign container-compatible
   ownership before first boot and put the data and backup destination on
   capacity-monitored storage.
2. Copy `env/production.env.example` to
   `/etc/detection-center/compose.env`; replace both example hostnames, all
   paths, and `ACME_EMAIL`. This file has no secret values.
3. Copy every `*.prod.env.example` file to the matching path under
   `/etc/detection-center/` declared by `*_ENV_FILE` in `compose.env`.
   Replace the OIDC and external HTTPS addresses. The runtime files remain
   outside the repository and are not tracked by Git.
4. Create exactly the root-owned `0400` files listed in
   [secrets/README.md](secrets/README.md) under `SECRETS_DIR`. The database,
   RabbitMQ, and Redis connection URL files must use Docker hostnames, while
   OIDC, partner, and notification URLs remain in non-secret env files.

The I7 services read their `*_FILE` settings from `/run/secrets`. A production
configuration must never contain `guest`, `ops-stub`, `localhost`,
`change-me-before-production`, or a non-HTTPS external OIDC/partner/notification
address.

## First deployment

Run all commands from the repository root. Set `COMPOSE_ENV_FILE` if the
environment file is not `/etc/detection-center/compose.env`.

```bash
export COMPOSE_ENV_FILE=/etc/detection-center/compose.env
deploy/compose/scripts/validate-production-config.sh
docker compose --env-file "$COMPOSE_ENV_FILE" -f deploy/compose/compose.prod.yaml --profile migration run --rm migrate
deploy/compose/scripts/bootstrap-acme.sh
docker compose --env-file "$COMPOSE_ENV_FILE" -f deploy/compose/compose.prod.yaml up --build -d --wait
docker compose --env-file "$COMPOSE_ENV_FILE" -f deploy/compose/compose.prod.yaml ps
```

The migration job is intentionally explicit and must succeed before the normal
application rollout. Application containers must not run Goose or any schema
DDL on startup. `bootstrap-acme.sh` creates a temporary certificate solely to
let Nginx serve the HTTP-01 challenge, replaces it with the issued certificate,
and reloads Nginx.

To verify the rendered topology without starting containers:

```bash
COMPOSE_ENV_FILE=/etc/detection-center/compose.env \
  deploy/compose/scripts/validate-production-config.sh
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml config
```

After images are built, validate the live Nginx configuration with:

```bash
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml exec -T nginx nginx -t
```

## Operations

All containers use bounded local JSON log rotation and structured stdout.
Forward Docker logs to the organization log platform; retain API audit data by
the approved data-retention policy, never by copying raw partner payloads into
logs. The on-call owner must receive alerts for: edge/API readiness, PostgreSQL
availability and free disk, RabbitMQ queue/DLQ depth and disk alarm, Redis
availability, Chroma health, failed backups, certificate expiry, and repeated
partner/notification failures. Record an owner and response target for each
alert in the team's operational system.

Run PostgreSQL and Chroma backups on a schedule and copy the resulting archives
to the approved off-server destination. Example manual commands:

```bash
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml --profile ops run --rm postgres-backup
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml --profile ops run --rm chroma-backup
```

RabbitMQ durable queues live on the host-controlled `data/rabbitmq` bind mount.
Protect that filesystem with the server backup policy and monitor its free
space and broker disk alarm; do not take ad-hoc live directory copies as a
substitute for a tested, quiesced restore procedure.

Schedule `scripts/renew-certificates.sh` at least daily; it is safe when no
renewal is due and reloads Nginx after the check. Retain backups according to
the organization policy and perform a documented restore drill at least once
per quarter on an isolated server.

For a restore drill, stop the writer services first, select a verified archive,
restore PostgreSQL and Chroma, then run readiness and business smoke checks
before reopening the edge:

```bash
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml stop api-go api-worker scheduler
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml --profile ops run --rm postgres-restore postgres-<timestamp>.dump
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml --profile ops run --rm chroma-restore chroma-<timestamp>.tgz
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml up -d api-go api-worker scheduler
```

## Upgrade and rollback

Before an upgrade, capture PostgreSQL and Chroma backups, render the target
configuration, run the explicit migration job, and retain the prior image
digests. Roll back application images only when the migration is backward
compatible; otherwise restore the matching database backup under the named
rollback owner's direction. Never roll back by deleting data volumes, RabbitMQ
durable storage, or secret files. Confirm `/healthz`, session login, a
center-scoped read, and queue health before declaring either rollout or
rollback complete.
