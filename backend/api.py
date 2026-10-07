import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.response import Response
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext

from db import SCHEMA, connect
from rules import judge

SECRET = os.environ.get("JWT_SECRET", "pvivscan-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "scanner": {"role": "writer", "password_hash": pwd.hash("scan123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}

REJECTION_REASON = "组串 {code} 被红外热像标记超温（在超温名单内），本次扫描整份拒收"


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
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅扫描员可操作")
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
    rejected_reason = None
    with connect() as conn:
        # 名单总开关行先锁，扳开关/点名与提交抢时刻时在此排队，
        # 保证"收下"与"挡回"只有一种收场，不会既进队列又挂超温。
        with conn.transaction():
            setting = conn.execute(
                "SELECT enabled FROM overtemp_settings WHERE id = 1 FOR UPDATE"
            ).fetchone()
            hit = conn.execute(
                """SELECT id FROM overtemp_strings
                   WHERE string_code = %s AND active = true""",
                (code,),
            ).fetchone()
            if setting is not None and setting["enabled"] and hit is not None:
                reason = REJECTION_REASON.format(code=code)
                # 挡回痕迹与拒收判定同一事务落库
                conn.execute(
                    """INSERT INTO overtemp_rejections
                       (string_code, voc_v, isc_a, fill_factor, list_enabled, reason,
                        created_by, rejected_by, rejected_at)
                       VALUES (%s,%s,%s,%s,true,%s,%s,'system',%s)""",
                    (code, voc, isc, ff, reason, user["username"], now),
                )
                rejected_reason = reason
            else:
                row = conn.execute(
                    """INSERT INTO iv_scans
                       (string_code, voc_v, isc_a, fill_factor, status, created_by, created_at)
                       VALUES (%s,%s,%s,%s,'pending',%s,%s)
                       RETURNING id, string_code, voc_v, isc_a, fill_factor, status, verdict,
                                 reason, created_by, created_at, processed_at""",
                    (code, voc, isc, ff, user["username"], now),
                ).fetchone()
        conn.commit()
    if rejected_reason is not None:
        raise HTTPException(status_code=409, detail=rejected_reason)
    return dump(row)


@get("/api/overtemp")
async def overtemp_state(request: Request) -> dict:
    need_login(request)
    with connect() as conn:
        setting = conn.execute(
            """SELECT enabled, updated_by, updated_at
               FROM overtemp_settings WHERE id = 1"""
        ).fetchone()
        strings = conn.execute(
            """SELECT id, string_code, active, created_by, created_at, updated_by, updated_at
               FROM overtemp_strings ORDER BY id DESC"""
        ).fetchall()
        rejections = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, list_enabled, reason,
                      created_by, rejected_by, rejected_at
               FROM overtemp_rejections ORDER BY id DESC LIMIT 100"""
        ).fetchall()
    return {
        "enabled": setting["enabled"] if setting else False,
        "updated_by": setting["updated_by"] if setting else None,
        "updated_at": setting["updated_at"].isoformat()
        if setting and setting["updated_at"] else None,
        "strings": [dump(r) for r in strings],
        "rejections": [dump(r) for r in rejections],
    }


@post("/api/overtemp/switch")
async def set_overtemp_switch(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    enabled = bool(data.get("enabled"))
    now = datetime.now(timezone.utc)
    with connect() as conn:
        with conn.transaction():
            # 与提交事务抢同一把行锁：开关落定前，该串送扫只能在锁后看新状态
            conn.execute("SELECT id FROM overtemp_settings WHERE id = 1 FOR UPDATE")
            row = conn.execute(
                """UPDATE overtemp_settings
                   SET enabled = %s, updated_by = %s, updated_at = %s
                   WHERE id = 1
                   RETURNING enabled, updated_by, updated_at""",
                (enabled, user["username"], now),
            ).fetchone()
        conn.commit()
    return dump(row)


@post("/api/overtemp/strings", status_code=201)
async def add_overtemp_string(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        with conn.transaction():
            conn.execute("SELECT id FROM overtemp_settings WHERE id = 1 FOR UPDATE")
            row = conn.execute(
                """INSERT INTO overtemp_strings
                   (string_code, active, created_by, created_at, updated_by, updated_at)
                   VALUES (%s, true, %s, %s, %s, %s)
                   ON CONFLICT (string_code) DO UPDATE
                     SET active = true,
                         updated_by = EXCLUDED.created_by,
                         updated_at = EXCLUDED.created_at
                   RETURNING id, string_code, active, created_by, created_at,
                             updated_by, updated_at""",
                (code, user["username"], now, user["username"], now),
            ).fetchone()
        conn.commit()
    return dump(row)


@post("/api/overtemp/strings/{string_id:int}/switch")
async def switch_overtemp_string(request: Request, string_id: int) -> dict:
    user = need_writer(request)
    data = await request.json()
    active = bool(data.get("active"))
    now = datetime.now(timezone.utc)
    with connect() as conn:
        with conn.transaction():
            conn.execute("SELECT id FROM overtemp_settings WHERE id = 1 FOR UPDATE")
            row = conn.execute(
                """UPDATE overtemp_strings
                   SET active = %s, updated_by = %s, updated_at = %s
                   WHERE id = %s
                   RETURNING id, string_code, active, created_by, created_at,
                             updated_by, updated_at""",
                (active, user["username"], now, string_id),
            ).fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="名单中没有这条组串")
    return dump(row)


app = Litestar(route_handlers=[
    health,
    login,
    list_logs,
    create_log,
    overtemp_state,
    set_overtemp_switch,
    add_overtemp_string,
    switch_overtemp_string,
])
