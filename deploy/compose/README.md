# Phase 5 / I1 deployment skeleton

This directory provides the minimum deploy-time skeleton required by `DEV_SPEC.md`
Phase 5 / I1:

- Docker Compose service topology for Go API/worker, AI service, scheduler,
  PostgreSQL, RabbitMQ, Redis, Chroma, edge Nginx, and controlled partner
  stubs.
- Chroma persistent storage, health checks, and backup/restore placeholders.
- Non-secret environment examples for container-to-container addresses.
- Basic observability plumbing through stdout logs plus optional Prometheus and
  blackbox-exporter profiles.

## Suggested local flow

1. Copy the example env files in `env/` into untracked runtime files if local
   overrides are needed.
2. Export real runtime secrets before starting Compose:
   - `INTERNAL_SERVICE_TOKEN`
   - `AI_SERVICE_SERVICE_BEARER_TOKEN`
   - `SCHEDULER_SERVICE_BEARER_TOKEN`
   - `SCHEDULER_CALLBACK_SERVICE_TOKEN`
3. Render and validate:

   ```bash
   docker compose -f deploy/compose/compose.yaml config
   ```

4. Start the stack:

   ```bash
   docker compose -f deploy/compose/compose.yaml up -d
   ```

## Chroma backup / restore placeholders

- Create a backup archive:

  ```bash
  docker compose -f deploy/compose/compose.yaml --profile ops run --rm chroma-backup
  ```

- Restore a known archive:

  ```bash
  CHROMA_RESTORE_ARCHIVE=<archive>.tgz \
  docker compose -f deploy/compose/compose.yaml --profile ops run --rm chroma-restore
  ```

These profile services intentionally operate only on the Chroma persistent
volume. Formal runbooks, drills, and recovery acceptance remain Phase 5 / I4.
