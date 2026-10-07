import os
import psycopg
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54402/pvivscan")


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


SCHEMA = """
CREATE TABLE IF NOT EXISTS iv_scans (
    id serial PRIMARY KEY,
    string_code text NOT NULL,
    voc_v double precision NOT NULL,
    isc_a double precision NOT NULL,
    fill_factor double precision NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    verdict text,
    reason text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    processed_at timestamptz
);
CREATE OR REPLACE FUNCTION notify_iv_scan() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('iv_scan_new', NEW.id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_iv_scan_notify ON iv_scans;
CREATE TRIGGER trg_iv_scan_notify
AFTER INSERT ON iv_scans
FOR EACH ROW EXECUTE FUNCTION notify_iv_scan();

-- 红外热像超温名单：点名入队后该组串的新扫描整份挡回
CREATE TABLE IF NOT EXISTS hot_strings (
    id serial PRIMARY KEY,
    string_code text NOT NULL UNIQUE,
    active boolean NOT NULL DEFAULT true,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_by text,
    updated_at timestamptz NOT NULL
);

-- 挡回痕迹：与真实拒收同事务写入，连同提交内容一并留档
CREATE TABLE IF NOT EXISTS block_traces (
    id serial PRIMARY KEY,
    string_code text NOT NULL,
    voc_v double precision NOT NULL,
    isc_a double precision NOT NULL,
    fill_factor double precision NOT NULL,
    submitted_by text NOT NULL,
    reason text NOT NULL,
    blocked_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_block_traces_string
    ON block_traces (string_code, blocked_at DESC);
"""
