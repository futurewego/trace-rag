# Deploy runbook

> Server: 阿里云香港轻量 2c4G / Ubuntu 22.04
> Path: `/opt/rag/`
> Plan: `docs/plans/2026-06-03-m1-deploy-v2.md`

## 首次部署

跟着 plan v2 走 T1-T10。

## 日常操作（cheat sheet）

### 状态

```bash
cd /opt/rag
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f --tail=100
```

### 更新代码

```bash
# 本地：commit + 打 tar
tar --exclude='.git' --exclude='.venv' --exclude='node_modules' \
    --exclude='.next' --exclude='uploads/*' \
    -czf /tmp/rag.tar.gz -C /Users/marvin/Desktop/ai_workspaces/test_rag .
scp /tmp/rag.tar.gz root@<server>:/opt/rag/

# 服务器：
cd /opt/rag && tar xzf rag.tar.gz && rm rag.tar.gz
docker compose -f docker-compose.prod.yml up -d --build
docker exec rag_backend alembic upgrade head  # 如有迁移
```

### 一键关 / 开（demo 完省钱）

```bash
docker compose -f docker-compose.prod.yml down       # 关
docker compose -f docker-compose.prod.yml up -d      # 开
```

### 看 retrieval 日志

```bash
docker exec rag_pg psql -U raguser -d ragdb -c \
  "SELECT id, query, chunks_sent_to_llm, retrieval_latency_ms, generation_latency_ms FROM retrieval_logs ORDER BY id DESC LIMIT 10"
```

### 重置（清空 DB 和 uploads，慎用）

```bash
docker compose -f docker-compose.prod.yml down -v   # -v = 删 volume
docker compose -f docker-compose.prod.yml up -d
docker exec rag_backend alembic upgrade head
```

## 备份

- 自动：`0 4 * * *` 跑 `backup.sh`，存 `/opt/rag/backups/`
- 保留 7 天

### 恢复 PG

```bash
gunzip -c /opt/rag/backups/pg_<date>.sql.gz | docker exec -i rag_pg psql -U raguser -d ragdb
```

### 恢复 uploads

```bash
docker run --rm -v rag_uploads:/u -v /opt/rag/backups:/b alpine \
  tar xzf /b/uploads_<date>.tar.gz -C /u
```

## 监控

- UptimeRobot 监控 `https://app.<yourdomain>`，关键字 `知识库问答`，5 分钟轮询
- Alert → 邮件 + Telegram bot
- only-alert when down > 10 min

## 故障排查

| 症状 | 检查 |
|---|---|
| 域名打不开 | `dig app.<yourdomain>` / 服务器防火墙 80,443 |
| 502 / 上游错误 | `docker compose logs frontend backend caddy` |
| Caddy 证书签发失败 | `docker logs rag_caddy 2>&1 \| grep -i cert` |
| /chat 报 500 | `docker logs rag_backend` 看 OpenAI/Claude 错误 |
| status 一直 parsing | `docker logs rag_backend` 看 ingestion 异常 |
| pg 启动失败 | `docker logs rag_pg`；检查 volume 权限 |
