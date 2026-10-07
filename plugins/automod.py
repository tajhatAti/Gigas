"""plugins/automod.py - link / shobdo / flood / forward auto mod"""
import re
import time
from collections import defaultdict, deque

import engine
from core import events, hub

_LINK_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/)", re.I)
_flood = defaultdict(deque)


def attach(hub_, client):
    client.add_event_handler(_on_message, events.NewMessage(incoming=True))


def _flood_hit(chat, user, count, seconds, now):
    q = _flood[(chat, user)]
    q.append(now)
    while q and now - q[0] > seconds:
        q.popleft()
    return len(q) >= count


def detect(am, text, ent_names, forwarded, now, chat, user):
    """Violation hole (kind, cfg) ferot dey, nahole None"""
    text = text or ""
    low = text.lower()
    lk = am["links"]
    if lk["on"]:
        has = bool(_LINK_RE.search(text)) or any(n in ("MessageEntityUrl", "MessageEntityTextUrl") for n in ent_names)
        if has and not any(a.lower() in low for a in lk["allow"] if a.strip()):
            return "links", lk
    wd = am["words"]
    if wd["on"] and any(w.lower() in low for w in wd["list"] if w.strip()):
        return "words", wd
    fw = am["forward"]
    if fw["on"] and forwarded:
        return "forward", fw
    fl = am["flood"]
    if fl["on"] and _flood_hit(chat, user, int(fl["count"]), int(fl["seconds"]), now):
        return "flood", fl
    return None


def build_actions(cfg):
    acts = [{"type": "delete", "optional": True}]
    a = cfg.get("action", "delete")
    if a == "warn":
        acts.append({"type": "warn"})
    elif a == "mute":
        acts.append({"type": "mute", "duration_min": int(cfg.get("mute_min", 10))})
    elif a == "ban":
        acts.append({"type": "ban", "duration_min": 0})
    return acts


async def _on_message(event):
    try:
        if not event.is_group:
            return
        chat_id, sender = event.chat_id, event.sender_id
        gc = hub.group_cfg(chat_id)
        am = gc["automod"]
        if not gc["enabled"] or not am["enabled"]:
            return
        if not sender or sender < 0 or sender == hub.me_id:
            return
        if sender in hub.trusted_ids() or await hub.is_protected(chat_id, sender):
            return
        m = event.message
        ent_names = [type(x).__name__ for x in (getattr(m, "entities", None) or [])]
        hit = detect(am, event.raw_text, ent_names, getattr(m, "fwd_from", None) is not None,
                     time.time(), chat_id, sender)
        if not hit:
            return
        kind, cfg = hit
        ctx = {"chat": chat_id, "user": sender, "by": hub.me_id, "msg_id": m.id, "msg_out": False}
        await engine.run_now(build_actions(cfg), ctx, f"automod:{kind}")
    except Exception as e:
        hub.log(kind="error", msg=f"automod: {type(e).__name__}: {e}")
