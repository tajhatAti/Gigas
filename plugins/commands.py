"""plugins/commands.py - reply dia command (.ban .mute 30m .promote ...)"""
import re

import engine
from core import events, hub, parse_duration


def attach(hub_, client):
    client.add_event_handler(_on_message, events.NewMessage())


async def _on_message(event):
    try:
        await _handle(event)
    except Exception as e:
        hub.log(kind="error", msg=f"command: {type(e).__name__}: {e}")


async def _resolve_user(tok):
    try:
        ref = tok if tok.startswith("@") else int(tok)
        return (await hub.entity(ref)).id
    except Exception:
        return None


def parse_args(argstr, have_target):
    """-> (target_ref_token | None, duration_min | None, text)"""
    target_tok, dur, rest = None, None, []
    for tok in argstr.split():
        if not have_target and target_tok is None and (tok.startswith("@") or re.fullmatch(r"-?\d{5,}", tok)):
            target_tok = tok
        elif dur is None and parse_duration(tok) is not None:
            dur = parse_duration(tok)
        else:
            rest.append(tok)
    return target_tok, dur, " ".join(rest)


async def _handle(event):
    text = event.raw_text or ""
    prefix = hub.cfg["settings"].get("prefix", ".") or "."
    if len(text) < 2 or not text.startswith(prefix) or not event.is_group:
        return
    by = event.sender_id
    if by != hub.me_id and not engine.trusted_entry(by):
        return
    m = re.match(rf"^{re.escape(prefix)}([A-Za-z0-9_]+)\s*(.*)$", text, re.S)
    if not m:
        return
    name, argstr = m.group(1).lower(), m.group(2).strip()
    chat_id = event.chat_id

    if name == "help":
        names = sorted({(r["trigger"].get("name") or "") for r in hub.cfg["rules"]
                        if r.get("enabled", True) and r["trigger"].get("type") == "command"})
        body = "Commands: " + ", ".join(prefix + n for n in names if n)
        if event.out:
            await event.edit(body)
        else:
            await event.reply(body)
        return

    if not engine.find_rules("command", name, chat_id):
        return

    reply = await event.get_reply_message() if event.is_reply else None
    target_id = reply.sender_id if reply else None
    tok, dur, rest = parse_args(argstr, target_id is not None)
    if target_id is None and tok:
        target_id = await _resolve_user(tok)
    args = {"duration_min": dur, "text": rest}
    n = engine.fire("command", name, chat_id, target_id, by, msg=reply, args=args)
    if n and hub.cfg["settings"].get("delete_command", True):
        try:
            await event.delete()
        except Exception:
            pass
