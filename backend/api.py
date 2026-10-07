import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.response import Response
from litestar.status_codes import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)
from passlib.context import CryptContext

from db import SCHEMA, connect
from rules import judge

SECRET = os.environ.get("JWT_SECRET", "pvivscan-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "scanner": {"role": "writer", "password_hash": pwd.hash("scan123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}


def dump(row):
    out = dict(row)
    for key, val in list(out.items()):
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat()
    return out


def seed():
    with connect() as conn:
        conn.execute(SCHEMA)
        n = conn.execute("SELECT COUNT(*) AS n FROM iv_scans").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("阵列A-串03", 41.2, 9.1, 0.78, "合格"),
                ("阵列B-串11", 38.0, 8.4, 0.61, "衰减"),
            ]
            for code, voc, isc, ff, expect in samples:
                verdict, reason = judge(ff)
                assert verdict == expect
                conn.execute(
                    """INSERT INTO iv_scans
                       (string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                        created_by, created_at, processed_at)
                       VALUES (%s,%s,%s,%s,'done',%s,%s,'scanner',%s,%s)""",
                    (code, voc, isc, ff, verdict, reason, now, now),
                )
        conn.commit()


seed()


def user_from(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(auth.split(" ", 1)[1].strip(), SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def need_login(request: Request):
    user = user_from(request)
    if user is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    return user


def need_writer(request: Request):
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅扫描员可提交IV扫描")
    return user


def need_operator(request: Request):
    """扳开关、点名入队等名单操作仅扫描员；观察员只读。"""
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="观察员只能查看，不能操作超温名单")
    return user


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "pv-string-iv-scan"}


@post("/api/auth/login")
async def login(request: Request) -> dict:
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return {"access_token": token, "username": username, "role": user["role"]}


@get("/api/logs")
async def list_logs(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                      created_by, created_at, processed_at
               FROM iv_scans ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@post("/api/logs", status_code=201)
async def create_log(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    try:
        voc = float(data.get("voc_v"))
        isc = float(data.get("isc_a"))
        ff = float(data.get("fill_factor"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="电压电流与填充因子必须是数字")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        # 按组串编号取咨询锁：与名单开关/点名操作互斥，
        # “关名单”和“入队”抢时刻时只会有一种收场，不会既收下又挂着超温。
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (code,))
        hot = conn.execute(
            "SELECT active FROM hot_strings WHERE string_code = %s FOR UPDATE",
            (code,),
        ).fetchone()
        if hot is not None and hot["active"]:
            reason = f"红外热像标记超温，组串 {code} 新扫描整份挡回"
            # 挡回痕迹与真实拒收在同一事务、同一批提交，绝无“拒收了却没留痕”。
            conn.execute(
                """INSERT INTO block_traces
                   (string_code, voc_v, isc_a, fill_factor, submitted_by, reason, blocked_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (code, voc, isc, ff, user["username"], reason, now),
            )
            conn.commit()
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=reason)
        row = conn.execute(
            """INSERT INTO iv_scans
               (string_code, voc_v, isc_a, fill_factor, status, created_by, created_at)
               VALUES (%s,%s,%s,%s,'pending',%s,%s)
               RETURNING id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                         created_by, created_at, processed_at""",
            (code, voc, isc, ff, user["username"], now),
        ).fetchone()
        conn.commit()
        return dump(row)


@get("/api/hot-list")
async def get_hot_list(request: Request) -> dict:
    need_login(request)
    with connect() as conn:
        entries = conn.execute(
            """SELECT id, string_code, active, created_by, created_at, updated_by, updated_at
               FROM hot_strings ORDER BY id DESC"""
        ).fetchall()
        traces = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, submitted_by, reason, blocked_at
               FROM block_traces ORDER BY id DESC LIMIT 200"""
        ).fetchall()
        return {"entries": [dump(r) for r in entries], "traces": [dump(r) for r in traces]}


@post("/api/hot-list", status_code=201)
async def add_hot_string(request: Request) -> dict:
    user = need_operator(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        # 与该串正在进行的提交互斥：入队完成后到达的提交必被挡，
        # 已在事务中的提交则先收下，绝不出现“又收下又挂着超温”。
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (code,))
        row = conn.execute(
            """INSERT INTO hot_strings (string_code, active, created_by, created_at, updated_at)
               VALUES (%s, true, %s, %s, %s)
               ON CONFLICT (string_code) DO UPDATE
                   SET active = true,
                       updated_by = EXCLUDED.created_by,
                       updated_at = EXCLUDED.created_at
               RETURNING id, string_code, active, created_by, created_at, updated_by, updated_at""",
            (code, user["username"], now, now),
        ).fetchone()
        conn.commit()
        return dump(row)


@post("/api/hot-list/switch")
async def switch_hot_string(request: Request) -> dict:
    user = need_operator(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    active = bool(data.get("active"))
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        # 与该串提交互斥：关掉名单后到达的提交必成功，名单开着的提交必失败。
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (code,))
        row = conn.execute(
            """UPDATE hot_strings
                  SET active = %s, updated_by = %s, updated_at = %s
                WHERE string_code = %s
            RETURNING id, string_code, active, created_by, created_at, updated_by, updated_at""",
            (active, user["username"], now, code),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="名单中没有该组串")
        conn.commit()
        return dump(row)


app = Litestar(
    route_handlers=[
        health,
        login,
        list_logs,
        create_log,
        get_hot_list,
        add_hot_string,
        switch_hot_string,
    ]
)
