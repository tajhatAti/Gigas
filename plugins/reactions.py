"""plugins/reactions.py - kono message e emoji react dile rule chalu"""
import asyncio
import time

import engine
from core import events, hub, norm_emoji, types, utils

_scheduled = set()


def attach(hub_, client):
    client.add_event_handler(_on_reaction, events.Raw(types.UpdateMessageReactions))


def my_emojis(msg):
    """Message e ami je emoji dilam tar set (chosen_order thakle seta amar)"""
    out = set()
    rx = getattr(msg, "reactions", None)
    for rc in (getattr(rx, "results", None) or []):
        if getattr(rc, "chosen_order", None) is None:
            continue
        e = getattr(getattr(rc, "reaction", None), "emoticon", None)
        if e:
            out.add(norm_emoji(e))
    return out


def _debug(chat_id, msg_id, upd, mine, note):
    rx = getattr(upd, "reactions", None)
    hub.react_debug.appendleft({
        "t": time.time(), "chat": chat_id, "msg": msg_id,
        "min": bool(getattr(rx, "min", False)), "mine": sorted(mine), "note": note,
    })


async def _on_reaction(update):
    try:
        chat_id = utils.get_peer_id(update.peer)
        if not hub.group_cfg(chat_id).get("enabled", True) or not engine.has_reaction_rules(chat_id):
            return
        await _trusted_scan(chat_id, update)
        key = (chat_id, update.msg_id)
        if key in _scheduled:
            return
        _scheduled.add(key)
        asyncio.create_task(_check(chat_id, update, key))
    except Exception as e:
        hub.log(kind="error", msg=f"reaction: {type(e).__name__}: {e}")


def _validator(ent, msg_id, emoji):
    async def v():
        m = await hub.client.get_messages(ent, ids=msg_id)
        return emoji in my_emojis(m)
    return v


async def _check(chat_id, update, key):
    msg_id = update.msg_id
    try:
        await asyncio.sleep(1.0)
    finally:
        _scheduled.discard(key)
    try:
        ent = await hub.entity(chat_id)
        msg = await hub.client.get_messages(ent, ids=msg_id)
        if not msg:
            return
        mine = my_emojis(msg)
        skey = f"{chat_id}:{msg_id}"
        prev = hub.react_state.get(skey, set())
        hub.react_state[skey] = mine
        if len(hub.react_state) > 5000:
            hub.react_state.pop(next(iter(hub.react_state)))
        new, removed = mine - prev, prev - mine
        for e in removed:
            hub.done_react.discard(f"{skey}:{e}")
        note = "kono notun react nai"
        for e in new:
            dkey = f"{skey}:{e}"
            if dkey in hub.done_react:
                note = f"{e}: aage-i kaj hoyeche"
                continue
            maxh = int(hub.cfg["settings"].get("react_max_age_h", 0) or 0)
            if maxh and msg.date and time.time() - msg.date.timestamp() > maxh * 3600:
                note = f"{e}: message onek purano ({maxh} ghonta er beshi)"
                continue
            if not engine.find_rules("reaction", e, chat_id):
                note = f"{e}: ei emoji te kono rule nai"
                continue
            sender = msg.sender_id
            if not sender or sender < 0 or sender == hub.me_id:
                note = f"{e}: message er pathok user na ba tumi nije"
                continue
            n = engine.fire("reaction", e, chat_id, sender, hub.me_id, msg=msg,
                            still_valid=_validator(ent, msg_id, e))
            if n:
                hub.done_react.add(dkey)
                note = f"{e}: {n} ta rule chalu hoyeche"
        if removed or new:
            hub.save_done_react()
        _debug(chat_id, msg_id, update, mine, note)
    except Exception as e:
        hub.log(kind="error", msg=f"reaction check: {type(e).__name__}: {e}")


async def _trusted_scan(chat_id, update):
    """Trusted moderator der react (jodi Telegram 'ke react dilo' jonaay)"""
    tids = hub.trusted_ids()
    recent = getattr(getattr(update, "reactions", None), "recent_reactions", None) or []
    if not tids or not recent:
        return
    for pr in recent:
        try:
            uid = utils.get_peer_id(pr.peer_id)
        except Exception:
            continue
        e = norm_emoji(getattr(getattr(pr, "reaction", None), "emoticon", "") or "")
        if uid not in tids or uid == hub.me_id or not e:
            continue
        dkey = f"{chat_id}:{update.msg_id}:{uid}:{e}"
        if dkey in hub.done_react:
            continue
        if not [r for r in engine.find_rules("reaction", e, chat_id) if engine.allowed(r, uid)]:
            continue
        ent = await hub.entity(chat_id)
        msg = await hub.client.get_messages(ent, ids=update.msg_id)
        if msg and msg.sender_id and msg.sender_id > 0 and msg.sender_id != hub.me_id:
            if engine.fire("reaction", e, chat_id, msg.sender_id, uid, msg=msg):
                hub.done_react.add(dkey)
                hub.save_done_react()
