# 光伏组串IV扫描台

扫描员提交组串开路电压、短路电流与填充因子。写入后走 PostgreSQL 通知通道叫醒独立工人，工人不轮询空转。填充因子不低于 0.72 为合格，否则衰减。页面是 Vue 3。

## 红外超温名单

顶栏“红外超温名单”进入专页，三列布局：左列扳开关、中列超温组串（点名入队）、右列挡回痕迹。

- 名单开启期间点名组串的**新扫描整份挡回**：`POST /api/logs` 返回 409，`iv_scans` 不落任何记录；
- **挡回痕迹与真实拒收在同一数据库事务、同一批提交**写入 `block_traces`，连同 Voc/Isc/FF、提交人一并留档，不会拒收了却没痕；
- 关掉名单后再送同一组串即正常入队；重复点名等于重新开启；
- “关名单/点名”与“该串提交”抢同一时刻时，按组串编号取 `pg_advisory_xact_lock` 串行，只有一种收场——要么收下且名单关着，要么挡回且名单开着，不会既收下又挂着超温；
- 观察员（watcher）能看名单与痕迹，扳开关/点名返回 403。

接口：`GET /api/hot-list`（登录可读）、`POST /api/hot-list`（writer 点名）、`POST /api/hot-list/switch`（writer 扳开关）。

## 技术栈

- 后端：Litestar、Uvicorn、psycopg 同步写入
- 工人：`LISTEN/NOTIFY` 唤醒后认领
- 前端：Vue 3、Vite、nginx 反代 `/api`

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3202 |
| 接口 | http://localhost:8202 |
| PostgreSQL | localhost:54402（库名 `pvivscan`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| scanner | scan123456 | 可提交 |
| watcher | watch123456 | 只读 |

## 启动

```bash
cd projects/22-pv-string-iv-scan
docker compose up --build
```

健康检查：`GET http://localhost:8202/api/health`

## 种子

| 组串 | 填充因子 | 结论 |
|------|----------|------|
| 阵列A-串03 | 0.78 | 合格 |
| 阵列B-串11 | 0.61 | 衰减 |
