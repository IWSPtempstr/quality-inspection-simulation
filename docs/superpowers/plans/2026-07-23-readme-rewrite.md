# README Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the obsolete root README with a Chinese, architecture-accurate guide for using the electrical product testing scheduling workbench.

**Architecture:** The root README is the entry document. It describes the React web application, Go API and worker, Python scheduler and AI services, and their PostgreSQL, RabbitMQ, Redis, and Chroma dependencies. It links to the detailed Compose runbook instead of duplicating production secrets and server operations.

**Tech Stack:** React 19, Vite, Go/Gin/Gorm, FastAPI, OR-Tools, PostgreSQL 16, RabbitMQ 4, Redis 7, Chroma, Docker Compose, Nginx, OIDC.

---

### Task 1: Replace The Root Project Guide

**Files:**
- Modify: `README.md`
- Verify: `README.md`, `deploy/compose/README.md`, `apps/web/package.json`

- [x] **Step 1: Establish the source-of-truth headings**

Use the current service layout and Compose documentation to give `README.md` these sections:

```markdown
# 电器产品检测排程工作台
## 功能概览
## 系统架构
## 角色与工作台
## 快速开始
## Docker Compose
## 配置说明
## 开发与验证
## 项目结构
## 文档与契约
```

- [x] **Step 2: Write the current architecture and bounded business flow**

Describe the production service flow without legacy technologies:

```text
React -> Go API -> PostgreSQL / RabbitMQ / Redis
                   -> Python scheduler
                   -> Python AI service -> Chroma
```

State that schedule candidates require human approval and version-checked partner write-back. Do not mention simulation, old runtimes, work-in-progress status, fake data, or removed features.

- [x] **Step 3: Add verified local and production usage commands**

Include the production-relevant `npm` scripts from `apps/web/package.json`, and point container users to these verified commands:

```bash
docker compose -f deploy/compose/compose.yaml up --build
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml --profile migration run --rm migrate
docker compose --env-file /etc/detection-center/compose.env \
  -f deploy/compose/compose.prod.yaml up --build -d --wait
```

Link to `deploy/compose/README.md` for secret files, TLS, backup, restore, and rollback instructions. Do not print secret values.

- [x] **Step 4: Validate documentation integrity**

Run:

```bash
git diff --check -- README.md docs/superpowers/plans/2026-07-23-readme-rewrite.md
rg -n 'FastAPI|SQLite|Jinja2|FAISS|LangGraph|MCP|仿真|欠缺|未完成' README.md
test -f deploy/compose/compose.prod.yaml
test -f deploy/compose/README.md
```

Expected: no whitespace errors; the prohibited legacy/background terms have no README matches; linked deployment documents exist.

- [x] **Step 5: Commit and publish the reviewed documentation**

```bash
git add README.md docs/superpowers/plans/2026-07-23-readme-rewrite.md
git commit -m "docs: rewrite project README"
git push origin main
```
