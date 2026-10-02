"""memory_engine.py — long-term memory (Mem0, local) + a daily Obsidian log.

    record_turn(user_msg, assistant_msg)   after each finished exchange
        - Mem0 distils durable facts / preferences from it and updates or
          removes the ones it contradicts (stored on this PC, memory/mem0_store)
        - one timestamped entry is appended to  <vault>/Daily/YYYY-MM-DD.md
    get_memory_context(query)              before a session / a Hermes task
        - the few stored memories most relevant to `query`, as a prompt block

Neither function ever raises: if Mem0 or the key is unavailable the Obsidian
log is still written and recall just returns "". record_turn() only queues the
work; one background thread does it, so the voice loop never waits.

Config (config/api_keys.json, all optional):
    obsidian_vault_path     default <Documents>/jarvis
    mem0_gemini_api_key     key Mem0 uses for fact extraction + embeddings;
                            falls back to hermes_gemini_api_key, then gemini_api_key
    mem0_llm_model          default gemini-flash-lite-latest
    memory_engine           false switches the whole thing off

Mem0's extraction step sends each exchange to Gemini (as the live
conversation already does).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

_BASE = Path(__file__).resolve().parent
_STORE = _BASE / "memory" / "mem0_store"
_USER_ID = "ido"
_LOG = _BASE / "logs" / "memory_engine.log"
_EMBED_DIMS = 768

_lock = threading.Lock()
_mem = None                 # the Mem0 instance, once built
_mem_failed_at = 0.0        # when building it last failed (retry after a while)
_queue: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=50)
_worker: threading.Thread | None = None


def _log(msg: str) -> None:
    try:
        _LOG.parent.mkdir(exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass


def _config() -> dict:
    try:
        return json.loads((_BASE / "config" / "api_keys.json").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def enabled() -> bool:
    return _config().get("memory_engine", True) is not False


def _vault() -> Path | None:
    candidates = [_config().get("obsidian_vault_path"),
                  Path.home() / "Documents" / "jarvis",
                  Path(r"C:\user\ido\documents\jarvis")]
    for c in candidates:
        if c and Path(str(c)).is_dir():
            return Path(str(c))
    return None


# ── Obsidian daily log ──────────────────────────────────────────────────────
def _append_daily(user_msg: str, assistant_msg: str) -> None:
    vault = _vault()
    if vault is None:
        _log("no Obsidian vault folder found — daily log skipped")
        return
    now = datetime.now()
    day = vault / "Daily" / f"{now:%Y-%m-%d}.md"
    day.parent.mkdir(parents=True, exist_ok=True)
    new = not day.exists()
    entry = f"\n### {now:%H:%M:%S}\n**You:** {user_msg}\n\n**JARVIS:** {assistant_msg}\n"
    with open(day, "a", encoding="utf-8") as f:
        if new:
            f.write(f"# {now:%A, %d %B %Y}\n")
        f.write(entry)


# ── Mem0 ────────────────────────────────────────────────────────────────────
def _get_mem():
    """Build Mem0 once (the first call takes a second or two). None if unavailable."""
    global _mem, _mem_failed_at
    if _mem is not None:
        return _mem
    with _lock:
        if _mem is not None:
            return _mem
        if time.time() - _mem_failed_at < 300:
            return None
        cfg = _config()
        key = next((str(cfg[k]).strip() for k in
                    ("mem0_gemini_api_key", "hermes_gemini_api_key", "gemini_api_key")
                    if str(cfg.get(k) or "").strip()), "")
        if not key:
            _mem_failed_at = time.time()
            _log("no Gemini key — Mem0 unavailable")
            return None
        try:
            from mem0 import Memory
            _STORE.mkdir(parents=True, exist_ok=True)
            _mem = Memory.from_config({
                "llm": {"provider": "gemini", "config": {
                    "model": str(cfg.get("mem0_llm_model") or "gemini-flash-lite-latest"),
                    "api_key": key, "temperature": 0.1}},
                "embedder": {"provider": "gemini", "config": {
                    "model": "models/gemini-embedding-001",
                    "api_key": key, "embedding_dims": _EMBED_DIMS}},
                "vector_store": {"provider": "qdrant", "config": {
                    "collection_name": "jarvis_memory", "path": str(_STORE),
                    "embedding_model_dims": _EMBED_DIMS, "on_disk": True}},
                "history_db_path": str(_STORE / "history.db"),
            })
            _log("Mem0 ready")
            # Register cleanup at interpreter exit so Qdrant doesn't
            # complain "sys.meta_path is None" during garbage collection.
            import atexit as _atexit
            _the_mem = _mem  # capture for closure
            def _close_qdrant(_m=_the_mem):
                try:
                    _m._vector_store.client.close()
                except Exception:
                    pass
            _atexit.register(_close_qdrant)
        except Exception as e:
            _mem_failed_at = time.time()
            _log(f"Mem0 could not start: {type(e).__name__}: {str(e)[:200]}")
            _mem = None
        return _mem


def _results(res) -> list:
    if isinstance(res, dict):
        res = res.get("results", [])
    return [r for r in (res or []) if isinstance(r, dict)]


def _remember(user_msg: str, assistant_msg: str) -> None:
    mem = _get_mem()
    if mem is None:
        return
    try:
        res = mem.add([{"role": "user", "content": user_msg},
                       {"role": "assistant", "content": assistant_msg}], user_id=_USER_ID)
        changes = [(r.get("event"), (r.get("memory") or "")[:80]) for r in _results(res)
                   if r.get("event") in ("ADD", "UPDATE", "DELETE")]
        if changes:
            _log(f"memory changes: {changes}")
    except Exception as e:
        _log(f"Mem0 add failed: {type(e).__name__}: {str(e)[:200]}")


def _run() -> None:
    while True:
        user_msg, assistant_msg = _queue.get()
        try:
            try:
                _append_daily(user_msg, assistant_msg)
            except Exception as e:
                _log(f"daily log failed: {type(e).__name__}: {e}")
            _remember(user_msg, assistant_msg)
        finally:
            _queue.task_done()


# ── public API ──────────────────────────────────────────────────────────────
def record_turn(user_msg: str, assistant_msg: str) -> None:
    """Queue one finished exchange; returns at once and never raises."""
    global _worker
    try:
        user_msg, assistant_msg = (user_msg or "").strip(), (assistant_msg or "").strip()
        if not (user_msg and assistant_msg) or not enabled():
            return
        with _lock:
            if _worker is None or not _worker.is_alive():
                _worker = threading.Thread(target=_run, daemon=True, name="memory-engine")
                _worker.start()
        _queue.put_nowait((user_msg, assistant_msg))
    except Exception as e:
        _log(f"record_turn: {type(e).__name__}: {e}")


def get_memory_context(query: str, limit: int = 6, timeout: float = 4.0) -> str:
    """The stored memories most relevant to `query`, as a ready prompt block ("" if none)."""
    try:
        if not enabled() or not (query or "").strip():
            return ""
        out: list = []

        def work():
            mem = _get_mem()
            if mem is None:
                return
            res = mem.search(query.strip(), filters={"user_id": _USER_ID}, top_k=limit)
            out.extend((r.get("memory") or "").strip() for r in _results(res) if r.get("memory"))

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(timeout)           # never hold up a connection for longer than this
        if not out:
            return ""
        return ("[WHAT YOU REMEMBER ABOUT THE USER]\n"
                + "\n".join(f"- {m}" for m in out[:limit])
                + "\nUse these naturally when relevant; never read the list aloud.\n")
    except Exception as e:
        _log(f"get_memory_context: {type(e).__name__}: {e}")
        return ""


def wait_until_stored(timeout: float = 90.0) -> None:
    """Block until queued exchanges are stored (tests / shutdown)."""
    end = time.time() + timeout
    while time.time() < end and _queue.unfinished_tasks:
        time.sleep(0.2)


def warmup() -> None:
    """Build Mem0 and run one tiny search now, in the background, so the first
    real recall (3.7 s cold, 0.4 s warm) happens before anyone speaks."""
    if not enabled():
        return

    def work():
        try:
            mem = _get_mem()
            if mem is not None:
                mem.search("warm-up", filters={"user_id": _USER_ID}, top_k=1)
                _log("warmed up")
        except Exception as e:
            _log(f"warmup: {type(e).__name__}: {str(e)[:120]}")

    threading.Thread(target=work, daemon=True, name="memory-warmup").start()
