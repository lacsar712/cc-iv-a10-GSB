# 光伏组串IV扫描台

扫描员提交组串开路电压、短路电流与填充因子。写入后走 PostgreSQL 通知通道叫醒独立工人，工人不轮询空转。填充因子不低于 0.72 为合格，否则衰减。页面是 Vue 3。

## 红外超温名单（整份拒收）

红外热像把某组串标记为超温时，该组串的新扫描要**整份退回**、不进 IV 队列：

- 顶栏「超温名单」进入专页，三列布局：左列开关、中列超温组串、右列挡回痕迹。
- 总开关打开并把组串「点名入队」后，该组串提交返回 `409`，扫描不写 `iv_scans`；关闭总开关（或关掉该串开关）后新单正常收下。
- 每次挡回都在**同一数据库事务**内写一条 `overtemp_rejections` 痕迹；没有真实拒收就不产生痕迹。
- 扳开关、点名与提交抢同一把行锁（`overtemp_settings` 单行 `FOR UPDATE`），并发时只有一种收场：要么收下、要么挡回，不会既入队又挂超温。
- 观察员（watcher）能看名单和痕迹，所有写操作返回 `403`。

接口：`GET /api/overtemp`、`POST /api/overtemp/switch`、`POST /api/overtemp/strings`、`POST /api/overtemp/strings/{id}/switch`（后三个仅扫描员）。


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
