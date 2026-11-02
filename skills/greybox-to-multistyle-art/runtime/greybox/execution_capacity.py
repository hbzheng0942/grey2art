"""Local, cross-process capacity ownership; project ledgers own task facts.

Reservations do not expire when a process or local lease dies. Only an explicit
not-accepted or remote-terminal observation may release a remote generation slot.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import time


class CapacityStore:
    def __init__(self, path, pools):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(str(self.path), timeout=2, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=2000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS pools (
                id TEXT PRIMARY KEY, capacity INTEGER NOT NULL,
                source_ref TEXT NOT NULL, cooldown_until REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS reservations (
                task_key TEXT PRIMARY KEY, pool TEXT NOT NULL,
                ledger_ref TEXT NOT NULL, created_at REAL NOT NULL,
                owner_pid INTEGER NOT NULL DEFAULT 0, claim_token TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS request_rates (
                pool TEXT NOT NULL, method TEXT NOT NULL, qps REAL,
                next_at REAL NOT NULL DEFAULT 0, PRIMARY KEY(pool,method));
        """)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            for key, config in pools.items():
                existing = self.db.execute("SELECT capacity FROM pools WHERE id=?", (key,)).fetchone()
                if existing is not None and existing[0] != config["capacity"]:
                    raise ValueError("Account pool capacity conflicts with another queue; explicitly reconcile the shared pool configuration")
                self.db.execute("INSERT OR IGNORE INTO pools(id,capacity,source_ref) VALUES(?,?,?)",
                                (key, config["capacity"], config["source_ref"]))
                for method, qps in config.get("rate_limits", {}).items():
                    previous = self.db.execute("SELECT qps FROM request_rates WHERE pool=? AND method=?", (key, method)).fetchone()
                    if previous and previous[0] is not None and previous[0] != qps:
                        raise ValueError("Account request-rate policy conflicts with another queue")
                    self.db.execute("INSERT INTO request_rates(pool,method,qps) VALUES(?,?,?) ON CONFLICT(pool,method) DO UPDATE SET qps=excluded.qps",
                                    (key, method, qps))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _existing(self, key, pool, ledger_ref):
        row = self.db.execute("SELECT pool,ledger_ref FROM reservations WHERE task_key=?", (key,)).fetchone()
        if row is not None and tuple(row) != (pool, ledger_ref):
            raise ValueError("The same task is already bound to a different account pool or ledger")
        return row is not None

    def reserve(self, key, pool, ledger_ref, *, adopt=False):
        """Reserve atomically, or adopt an already-existing remote job even if full."""
        ledger_ref = str(ledger_ref)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self._existing(key, pool, ledger_ref):
                self.db.execute("COMMIT")
                return True
            config = self.db.execute("SELECT capacity,cooldown_until FROM pools WHERE id=?", (pool,)).fetchone()
            if config is None:
                raise ValueError("Task refers to an undeclared account pool")
            count = self.db.execute("SELECT COUNT(*) FROM reservations WHERE pool=?", (pool,)).fetchone()[0]
            if not adopt and (count >= config[0] or config[1] > time.time()):
                self.db.execute("COMMIT")
                return False
            self.db.execute("INSERT INTO reservations(task_key,pool,ledger_ref,created_at) VALUES(?,?,?,?)", (key, pool, ledger_ref, time.time()))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def claim_pending(self, key, pool, ledger_ref, token, owner_pid):
        """Exclusive local dispatch claim, only for a ledger-confirmed unsent task.

        Dead-owner takeover here does not release a remote slot. The scheduler
        calls this only when its source ledger has no submitted task or action
        lease; active/unknown jobs are adopted with reserve(adopt=True).
        """
        ledger_ref = str(ledger_ref)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT pool,ledger_ref,owner_pid,claim_token FROM reservations WHERE task_key=?", (key,)).fetchone()
            if row:
                if tuple(row[:2]) != (pool, ledger_ref):
                    raise ValueError("Task account binding changed")
                if row[3] == token:
                    self.db.execute("COMMIT")
                    return True
                owner_alive = False
                if row[2] > 0:
                    try:
                        os.kill(row[2], 0)
                        owner_alive = True
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        owner_alive = True
                if owner_alive:
                    self.db.execute("COMMIT")
                    return False
                self.db.execute("UPDATE reservations SET owner_pid=?,claim_token=? WHERE task_key=?",
                                (owner_pid, token, key))
                self.db.execute("COMMIT")
                return True
            config = self.db.execute("SELECT capacity,cooldown_until FROM pools WHERE id=?", (pool,)).fetchone()
            if config is None:
                raise ValueError("Task refers to an undeclared account pool")
            count = self.db.execute("SELECT COUNT(*) FROM reservations WHERE pool=?", (pool,)).fetchone()[0]
            if count >= config[0] or config[1] > time.time():
                self.db.execute("COMMIT")
                return False
            self.db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?)",
                            (key, pool, ledger_ref, time.time(), owner_pid, token))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def release_claim(self, key, token):
        """Release only our known-unsent claim, never another dispatch's slot."""
        self.db.execute("DELETE FROM reservations WHERE task_key=? AND claim_token=?", (key, token))

    def release(self, key):
        """Caller must have a bound explicit terminal/not-accepted observation."""
        self.db.execute("DELETE FROM reservations WHERE task_key=?", (key,))

    def contains(self, key):
        return self.db.execute("SELECT 1 FROM reservations WHERE task_key=?", (key,)).fetchone() is not None

    def cooldown(self, pool, seconds):
        until = time.time() + max(0., float(seconds))
        self.db.execute("UPDATE pools SET cooldown_until=MAX(cooldown_until,?) WHERE id=?", (until, pool))

    def cooldown_action(self, pool, method, seconds):
        until = time.time() + max(0., float(seconds))
        self.db.execute("INSERT INTO request_rates(pool,method,qps,next_at) VALUES(?,?,NULL,?) ON CONFLICT(pool,method) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
                        (pool, method, until))

    def rate_wait(self, pool, method):
        row = self.db.execute("SELECT next_at FROM request_rates WHERE pool=? AND method=?", (pool, method)).fetchone()
        return max(0., row[0] - time.time()) if row else 0.

    def allow_action(self, pool, method):
        """Reserve one method dispatch time atomically across all queue owners."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT qps,next_at FROM request_rates WHERE pool=? AND method=?", (pool, method)).fetchone()
            now = time.time()
            allowed = row is None or row[1] <= now
            if allowed and row is not None and row[0] is not None:
                self.db.execute("UPDATE request_rates SET next_at=? WHERE pool=? AND method=?", (now + 1. / row[0], pool, method))
            self.db.execute("COMMIT")
            return allowed
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def available(self, pool):
        config = self.db.execute("SELECT capacity,cooldown_until FROM pools WHERE id=?", (pool,)).fetchone()
        if config is None:
            raise ValueError("Undeclared account pool")
        if config[1] > time.time():
            return 0
        count = self.db.execute("SELECT COUNT(*) FROM reservations WHERE pool=?", (pool,)).fetchone()[0]
        return max(0, config[0] - count)

    def snapshot(self):
        result = {}
        for pool, capacity, until in self.db.execute("SELECT id,capacity,cooldown_until FROM pools ORDER BY id"):
            count = self.db.execute("SELECT COUNT(*) FROM reservations WHERE pool=?", (pool,)).fetchone()[0]
            result[pool] = {"capacity": capacity, "occupied": count,
                            "available": max(0, capacity - count), "cooldown_until": until,
                            "rate_limits": {method: {"qps": qps, "next_at": next_at} for method, qps, next_at in
                                self.db.execute("SELECT method,qps,next_at FROM request_rates WHERE pool=?", (pool,))}}
        return result
