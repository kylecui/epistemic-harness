"""Shared-Pool 3-Window Rolling Quota Ledger (5h / week / month),
Peak-Hour Multiplier & Avoidance, and Last-Option Reserve Manager.

Key design:
  - Multiple models under the same CodingPlan share ONE Pool (`pool_id`).
  - Each model has its own `cost_per_1m` weights (input / cached_input / output).
  - Usage is recorded in pool-native units (credits or USD) with optional
    `peak_cost_multiplier` (e.g. 2.0x during peak hours on OpenCode Go).
  - When a shared pool exhausts ANY of its 5h / week (168h) / month (720h)
    rolling limits, ALL models sharing that pool are immediately skipped and
    traffic automatically fails over to the next healthy pool.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

import yaml

WINDOW_SPECS: tuple[tuple[str, float, str], ...] = (
    ("5h", 5.0, "rolling_5h_limit"),
    ("week", 168.0, "rolling_week_limit"),
    ("month", 720.0, "rolling_month_limit"),
)


@dataclass(frozen=True)
class ModelSelection:
    model_key: str
    pool_id: str
    upstream_model: str
    upstream_base_url: str
    api_key_env: str | None
    protocol: str
    failover_chain: list[str]
    skipped_reasons: dict[str, str]
    peak_avoided: bool
    last_option_used: bool


def _parse_hhmm(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def is_in_peak_window(now_utc: datetime, peak_windows_utc: list[dict[str, str]]) -> bool:
    cur_min = now_utc.hour * 60 + now_utc.minute
    for win in peak_windows_utc:
        start_m = _parse_hhmm(win["start"])
        end_m = _parse_hhmm(win["end"])
        if start_m <= end_m:
            if start_m <= cur_min < end_m:
                return True
        else:
            if cur_min >= start_m or cur_min < end_m:
                return True
    return False


class QuotaManager:
    def __init__(self, policy_path: Path, db_path: Path) -> None:
        self.policy_path = policy_path
        self.db_path = db_path
        self.policy: dict[str, Any] = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        self.pools: dict[str, dict[str, Any]] = self.policy.get("pools", {})
        self.models: dict[str, dict[str, Any]] = self.policy.get("models", {})
        self.routing_chains: dict[str, list[str]] = self.policy.get("routing_chains", {})
        self.agent_profiles: dict[str, dict[str, Any]] = self.policy.get("agent_profiles", {})
        self.soft_limit_ratio: float = float(self.policy.get("soft_limit_ratio", 0.95))
        self.active_peak_avoidance: bool = bool(self.policy.get("active_peak_avoidance", True))
        self.default_cooldown_sec: int = int(self.policy.get("default_cooldown_seconds", 300))
        self._pool_cooldowns: dict[str, datetime] = {}
        # Model-scoped cooldowns for misconfiguration-class failures (401/403/404/5xx).
        self._model_cooldowns: dict[str, tuple[datetime, str]] = {}
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pool_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc REAL NOT NULL,
                    pool_id TEXT NOT NULL,
                    model_key TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    cached_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    thinking_tokens INTEGER NOT NULL,
                    units_consumed REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pool_usage_ts ON pool_usage(pool_id, ts_utc)")

    def pool_for_model(self, model_key: str) -> tuple[str, dict[str, Any]]:
        pool_id = str(self.models[model_key]["pool"])
        return pool_id, self.pools[pool_id]

    def is_last_option(self, model_key: str) -> bool:
        _, pool_cfg = self.pool_for_model(model_key)
        return bool(pool_cfg.get("last_option", False))

    @staticmethod
    def _clean_env(val: str | None) -> str | None:
        """Strip surrounding quotes: .env files often write KEY="value", and
        Docker --env-file / compose env_file pass the raw quoted string through."""
        if not val:
            return val
        return val.strip().strip('"').strip("'").strip()

    def resolve_upstream_url(self, model_key: str, fallback_url: str) -> str:
        cfg = self.models.get(model_key, {})
        env_name = cfg.get("upstream_base_url_env")
        env_val = self._clean_env(os.getenv(env_name)) if env_name else None
        if env_val:
            return env_val.rstrip("/")
        if cfg.get("default_base_url"):
            return str(cfg["default_base_url"]).rstrip("/")
        return fallback_url.rstrip("/")

    def resolve_api_key(self, model_key: str) -> str | None:
        cfg = self.models.get(model_key, {})
        env_name = cfg.get("api_key_env")
        return self._clean_env(os.getenv(env_name)) if env_name else None

    def compute_units(
        self,
        model_key: str,
        prompt_tokens: int,
        completion_tokens: int,
        thinking_tokens: int = 0,
        cached_tokens: int = 0,
        now_utc: datetime | None = None,
    ) -> float:
        now = now_utc or datetime.now(timezone.utc)
        mcfg = self.models[model_key]
        _, pcfg = self.pool_for_model(model_key)
        rates = mcfg.get("cost_per_1m", {"input": 1.0, "cached_input": 0.25, "output": 4.0})
        billable_input = max(0, prompt_tokens - cached_tokens)
        total_out = max(0, completion_tokens) + max(0, thinking_tokens)

        base_units = (
            (billable_input / 1_000_000.0) * float(rates.get("input", 1.0))
            + (max(0, cached_tokens) / 1_000_000.0) * float(rates.get("cached_input", 0.25))
            + (total_out / 1_000_000.0) * float(rates.get("output", 4.0))
        )
        in_peak = is_in_peak_window(now, pcfg.get("peak_windows_utc", []))
        mult = float(pcfg.get("peak_cost_multiplier", 1.0)) if in_peak else 1.0
        return base_units * mult

    def record_usage(
        self,
        model_key: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        thinking_tokens: int = 0,
        cached_tokens: int = 0,
        units_override: float | None = None,
        now_utc: datetime | None = None,
    ) -> float:
        now = now_utc or datetime.now(timezone.utc)
        pool_id, _ = self.pool_for_model(model_key)
        units = (
            float(units_override)
            if units_override is not None
            else self.compute_units(model_key, prompt_tokens, completion_tokens, thinking_tokens, cached_tokens, now)
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO pool_usage "
                "(ts_utc, pool_id, model_key, prompt_tokens, cached_tokens, completion_tokens, thinking_tokens, units_consumed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now.timestamp(), pool_id, model_key, prompt_tokens, cached_tokens, completion_tokens, thinking_tokens, units),
            )
        return units

    def get_pool_window_units(self, pool_id: str, hours: float, now_utc: datetime | None = None) -> float:
        now = now_utc or datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=hours)).timestamp()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(units_consumed), 0.0) FROM pool_usage WHERE pool_id = ? AND ts_utc >= ?",
                (pool_id, cutoff),
            ).fetchone()
        return float(row[0] if row else 0.0)

    def mark_rate_limited(
        self, model_key: str, retry_after_sec: int | None = None, now_utc: datetime | None = None
    ) -> datetime:
        now = now_utc or datetime.now(timezone.utc)
        pool_id, _ = self.pool_for_model(model_key)
        wait_s = retry_after_sec if (retry_after_sec is not None and retry_after_sec > 0) else self.default_cooldown_sec
        until = now + timedelta(seconds=wait_s)
        self._pool_cooldowns[pool_id] = until
        return until

    # ---- upstream failure classification (authoritative signal; the local ledger is only an estimate) ----
    _BODY_RESET_TS = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")
    _WINDOW_HINT = re.compile(r"5[\s-]?hour|5\s*小时", re.IGNORECASE)
    BODY_TZ = timezone(timedelta(hours=8))  # naive timestamps in provider error bodies (CN providers) are UTC+8 [L3]

    def _parse_body_reset(self, body_text: str, now: datetime) -> datetime | None:
        m = self._BODY_RESET_TS.search(body_text or "")
        if not m:
            return None
        try:
            naive = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        until = naive.replace(tzinfo=self.BODY_TZ).astimezone(timezone.utc)
        return until if now < until <= now + timedelta(days=8) else None

    def mark_upstream_failure(
        self,
        model_key: str,
        status: int,
        body_text: str = "",
        retry_after_sec: int | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply a cooldown by failure class. 429/529 -> shared pool; 401/403/404/5xx -> this model only."""
        now = now_utc or datetime.now(timezone.utc)
        if status in (429, 529):
            if retry_after_sec and retry_after_sec > 0:
                until = self.mark_rate_limited(model_key, retry_after_sec, now_utc=now)
            else:
                reset = self._parse_body_reset(body_text, now)
                if reset is not None:
                    pool_id, _ = self.pool_for_model(model_key)
                    self._pool_cooldowns[pool_id] = reset
                    until = reset
                elif self._WINDOW_HINT.search(body_text or ""):
                    until = self.mark_rate_limited(model_key, 900, now_utc=now)
                else:
                    until = self.mark_rate_limited(model_key, None, now_utc=now)
            return {"scope": "pool", "until": until, "reason": "rate_limited"}
        if status in (401, 403):
            reason, wait_s = "auth_failed", 3600
        elif status == 404:
            reason, wait_s = "endpoint_not_found", 3600
        elif status >= 500:
            reason, wait_s = "upstream_5xx", 60
        else:
            return {"scope": "none", "until": None, "reason": f"http_{status}"}
        until = now + timedelta(seconds=wait_s)
        self._model_cooldowns[model_key] = (until, reason)
        return {"scope": "model", "until": until, "reason": reason}

    def _check_availability(
        self, model_key: str, tier: str, now_utc: datetime
    ) -> tuple[bool, bool, str | None]:
        mcfg = self.models[model_key]
        pool_id, pcfg = self.pool_for_model(model_key)

        # 0. Model-scoped cooldown (auth/endpoint/5xx failures)
        mcd = self._model_cooldowns.get(model_key)
        if mcd and now_utc < mcd[0]:
            rem = int((mcd[0] - now_utc).total_seconds())
            return (False, False, f"model_{mcd[1]}({rem}s)")

        # 1. Shared-pool 429 cooldown
        cd = self._pool_cooldowns.get(pool_id)
        if cd and now_utc < cd:
            rem = int((cd - now_utc).total_seconds())
            return (False, False, f"pool_{pool_id}_cooldown({rem}s)")

        # 2. Shared-pool 5h / week / month rolling quota check
        for label, hours, limit_key in WINDOW_SPECS:
            limit_val = pcfg.get(limit_key)
            if limit_val is None:
                continue
            lim = float(limit_val)
            used = self.get_pool_window_units(pool_id, hours, now_utc)
            if used >= lim * self.soft_limit_ratio:
                return (False, False, f"pool_{pool_id}_{label}_exhausted({used:.1f}/{lim:.1f})")

        # 3. Global active peak-hour avoidance (yields to off-peak / no-peak primary pools)
        in_peak = is_in_peak_window(now_utc, pcfg.get("peak_windows_utc", []))
        avoid_tiers = set(mcfg.get("avoid_in_peak_for_tiers", []))
        if in_peak and (self.active_peak_avoidance or tier in avoid_tiers):
            return (True, True, f"peak_hour_yielded({pool_id})")

        return (True, False, None)

    def select_candidates(
        self,
        tier: str,
        protocol: str,
        requested_model: str | None = None,
        now_utc: datetime | None = None,
        fallback_base_url: str = "",
        exclude_pool: str | None = None,
    ) -> ModelSelection:
        now = now_utc or datetime.now(timezone.utc)
        base_chain = list(self.routing_chains.get(tier, list(self.models.keys())))
        proto_chain = [m for m in base_chain if m in self.models and self.models[m].get("protocol") == protocol]
        if not proto_chain:
            proto_chain = [m for m in base_chain if m in self.models]

        if requested_model and requested_model in proto_chain and not self.is_last_option(requested_model):
            proto_chain = [requested_model] + [m for m in proto_chain if m != requested_model]

        primary_off_peak: list[str] = []
        primary_peak_dep: list[str] = []
        last_option_pool: list[str] = []
        skipped: dict[str, str] = {}

        deprioritized_same_family: list[str] = []
        for mkey in proto_chain:
            is_last = self.is_last_option(mkey)
            m_pool, _ = self.pool_for_model(mkey)
            ok, is_peak_dep, reason = self._check_availability(mkey, tier, now)
            if not ok:
                skipped[mkey] = reason or "unavailable"
                continue
            if is_last:
                last_option_pool.append(mkey)
                skipped[mkey] = "held_in_last_option_reserve"
            elif exclude_pool and m_pool == exclude_pool:
                deprioritized_same_family.append(mkey)
                skipped[mkey] = f"cross_family_critic_excluded({exclude_pool})"
            elif is_peak_dep:
                primary_peak_dep.append(mkey)
                skipped[mkey] = reason or "peak_hour_yielded"
            else:
                primary_off_peak.append(mkey)

        ordered = primary_off_peak + primary_peak_dep + deprioritized_same_family + last_option_pool
        if not ordered:
            # Everything is unavailable. Probe ONLY the candidate that recovers soonest instead of
            # hammering every dead pool on every request (failure reasons are surfaced by the gateway).
            def _recover_at(mk: str) -> datetime:
                pid, _ = self.pool_for_model(mk)
                cands = [now]
                if mk in self._model_cooldowns:
                    cands.append(self._model_cooldowns[mk][0])
                if pid in self._pool_cooldowns:
                    cands.append(self._pool_cooldowns[pid])
                return max(cands)

            ordered = [min(proto_chain, key=_recover_at)]

        chosen = ordered[0]
        chosen_pool, _ = self.pool_for_model(chosen)
        peak_avoided = bool(primary_peak_dep and chosen in primary_off_peak)
        last_option_used = self.is_last_option(chosen)
        return ModelSelection(
            model_key=chosen,
            pool_id=chosen_pool,
            upstream_model=self.models[chosen]["upstream_model"],
            upstream_base_url=self.resolve_upstream_url(chosen, fallback_base_url),
            api_key_env=self.models[chosen].get("api_key_env"),
            protocol=self.models[chosen]["protocol"],
            failover_chain=ordered,
            skipped_reasons=skipped,
            peak_avoided=peak_avoided,
            last_option_used=last_option_used,
        )

    def status_snapshot(self, now_utc: datetime | None = None) -> dict[str, Any]:
        now = now_utc or datetime.now(timezone.utc)
        pools_out: dict[str, Any] = {}
        for pid, pcfg in self.pools.items():
            windows_info: dict[str, Any] = {}
            for label, hours, limit_key in WINDOW_SPECS:
                lim = float(pcfg.get(limit_key, 1.0))
                used = self.get_pool_window_units(pid, hours, now)
                windows_info[label] = {
                    "used": round(used, 3),
                    "limit": lim,
                    "pct": round(100.0 * used / max(1e-6, lim), 2),
                }
            cd = self._pool_cooldowns.get(pid)
            cd_rem = max(0, int((cd - now).total_seconds())) if cd else 0
            pools_out[pid] = {
                "unit": pcfg.get("unit", "credits"),
                "last_option": bool(pcfg.get("last_option", False)),
                "in_peak_hour": is_in_peak_window(now, pcfg.get("peak_windows_utc", [])),
                "peak_cost_multiplier": float(pcfg.get("peak_cost_multiplier", 1.0)),
                "models": [mk for mk, mc in self.models.items() if mc.get("pool") == pid],
                "windows": windows_info,
                "cooldown_remaining_sec": cd_rem,
            }
        return {"ts_utc": now.isoformat(), "pools": pools_out}
