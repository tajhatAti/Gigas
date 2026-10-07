"""actions.py - ban, mute, promote ... sob kaj ekhane"""
import asyncio
from datetime import datetime, timedelta, timezone

from core import DEFAULT_RIGHTS, FLOOD, flood_secs, functions, hub, types

RIGHT_BN = {
    "ban_users": "ban/mute korar", "delete_messages": "message delete korar",
    "add_admins": "admin banano", "invite_users": "invite korar", "pin_messages": "pin korar",
}

ERRS = {
    "ChatAdminRequiredError": "Tomar admin adhikar nei",
    "UserAdminInvalidError": "Ei user admin, tar upor kaj kora jabe na",
    "ChatAdminInviteRequiredError": "Invite korar adhikar nei",
    "UserPrivacyRestrictedError": "User er privacy te add kora jay na",
    "UserNotMutualContactError": "User mutual contact na, add kora jay na",
    "UserIdInvalidError": "User paoa jayni",
    "PeerIdInvalidError": "Chat/User paoa jayni",
    "ChatWriteForbiddenError": "Ekhane pathano jabe na",
    "MessageDeleteForbiddenError": "Message delete korar adhikar nei",
    "UserCreatorError": "Group owner er upor kaj kora jay na",
    "RightForbiddenError": "Ei adhikar dewar onumoti nei",
    "ParticipantIdInvalidError": "User ei group e nai",
    "UserNotParticipantError": "User ei group e nai",
    "PeerFloodError": "Telegram onek add/message block koreche (PeerFlood), pore cheshta koro",
}


def ok(msg, undo=None):
    return {"ok": True, "msg": msg, "undo": undo}


def fail(msg):
    return {"ok": False, "msg": msg, "undo": None}


def readable(e):
    return ERRS.get(type(e).__name__) or f"{type(e).__name__}: {str(e)[:150]}"


class _D(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def fmt(text, ctx):
    vals = _D(name=ctx.get("user_name", ""), user=ctx.get("user_name", ""), id=ctx.get("user", ""),
              group=ctx.get("chat_title", ""), by=ctx.get("by_name", ""))
    try:
        return str(text).format_map(vals)
    except Exception:
        return str(text)


def _until(mins):
    try:
        mins = int(mins or 0)
    except Exception:
        mins = 0
    return datetime.now(timezone.utc) + timedelta(minutes=mins) if mins > 0 else None


async def _guard(ctx, right=None, protect=False, need_user=True):
    if need_user:
        if not ctx.get("user"):
            return fail("Target user paoa jayni (message e reply dao ba @user likho)")
        if ctx["user"] == hub.me_id:
            return fail("Nijer upor kaj kora jabe na")
    ent = await hub.entity(ctx["chat"])
    if right and await hub.has_right(ent, right) is False:
        return fail("Ei group e tomar " + RIGHT_BN.get(right, right) + " adhikar nei")
    if protect and await hub.is_protected(ctx["chat"], ctx["user"]):
        return fail("Ei user surokkhito (admin / protected list e ache)")
    return None


async def _delete_all(ent, uid):
    if isinstance(ent, types.Channel):
        try:
            await hub.client(functions.channels.DeleteParticipantHistoryRequest(channel=ent, participant=uid))
            return -1
        except Exception:
            pass
    ids = []
    async for m in hub.client.iter_messages(ent, from_user=uid, limit=300):
        ids.append(m.id)
    if ids:
        await hub.client.delete_messages(ent, ids)
    return len(ids)


# ---------------- handlers ----------------
async def a_ban(act, ctx):
    g = await _guard(ctx, "ban_users", protect=True)
    if g:
        return g
    ent = await hub.entity(ctx["chat"])
    mins = ctx.get("duration_min") or act.get("duration_min") or 0
    await hub.client.edit_permissions(ent, ctx["user"], until_date=_until(mins), view_messages=False)
    extra = ""
    if act.get("delete_history"):
        await _delete_all(ent, ctx["user"])
        extra = " + sob message muchlo"
    return ok("Ban" + (f" ({int(mins)} min)" if mins else "") + extra,
              {"type": "unban", "chat": ctx["chat"], "user": ctx["user"]})


async def a_mute(act, ctx):
    g = await _guard(ctx, "ban_users", protect=True)
    if g:
        return g
    ent = await hub.entity(ctx["chat"])
    mins = ctx.get("duration_min") or act.get("duration_min") or 0
    await hub.client.edit_permissions(
        ent, ctx["user"], until_date=_until(mins), send_messages=False, send_media=False,
        send_stickers=False, send_gifs=False, send_games=False, send_inline=False,
        embed_link_previews=False, send_polls=False)
    return ok("Mute" + (f" ({int(mins)} min)" if mins else " (cholbe jotokkhon na unmute kori)"),
              {"type": "unmute", "chat": ctx["chat"], "user": ctx["user"]})


async def a_unban(act, ctx):
    g = await _guard(ctx, "ban_users")
    if g:
        return g
    ent = await hub.entity(ctx["chat"])
    await hub.client.edit_permissions(ent, ctx["user"])
    return ok("Unban/Unmute hoyeche")


a_unmute = a_unban


async def a_kick(act, ctx):
    g = await _guard(ctx, "ban_users", protect=True)
    if g:
        return g
    ent = await hub.entity(ctx["chat"])
    await hub.client.kick_participant(ent, ctx["user"])
    return ok("Kick hoyeche (abar join korte parbe)")


async def a_warn(act, ctx):
    g = await _guard(ctx, "ban_users", protect=True)
    if g:
        return g
    st = hub.cfg["settings"]
    limit = max(1, int(st.get("warn_limit", 3)))
    n = hub.warn_add(ctx["chat"], ctx["user"], 1)
    msg = f"Warn {n}/{limit}"
    if st.get("notify_in_chat"):
        try:
            ent = await hub.entity(ctx["chat"])
            await hub.client.send_message(ent, f"⚠ {ctx.get('user_name', '')} — warn {n}/{limit}")
        except Exception:
            pass
    if n >= limit:
        hub.warn_reset(ctx["chat"], ctx["user"])
        kind = st.get("warn_action", "mute")
        if kind not in ("ban", "mute", "kick"):
            kind = "mute"
        res = await run({"type": kind, "duration_min": int(st.get("warn_mute_min", 1440))}, ctx)
        return {"ok": res["ok"], "msg": msg + " -> limit shesh, " + res["msg"], "undo": res["undo"]}
    return ok(msg, {"type": "unwarn", "chat": ctx["chat"], "user": ctx["user"]})


async def a_unwarn(act, ctx):
    if not ctx.get("user"):
        return fail("Target user paoa jayni")
    n = hub.warn_add(ctx["chat"], ctx["user"], -1)
    return ok(f"Warn kombe gelo, ekhon {n}")


async def a_delete(act, ctx):
    mid = ctx.get("msg_id")
    if not mid:
        return fail("Kon message delete korbo? (message e reply dao)")
    ent = await hub.entity(ctx["chat"])
    if not ctx.get("msg_out") and await hub.has_right(ent, "delete_messages") is False:
        return fail("Ei group e tomar message delete korar adhikar nei")
    await hub.client.delete_messages(ent, [mid])
    return ok("Message muche dewa hoyeche")


async def a_delete_all(act, ctx):
    g = await _guard(ctx, "delete_messages", protect=True)
    if g:
        return g
    ent = await hub.entity(ctx["chat"])
    n = await _delete_all(ent, ctx["user"])
    return ok("Oi user er sob message muche dewa hoyeche" if n < 0 else f"{n} ta message muche dewa hoyeche")


async def a_promote(act, ctx):
    g = await _guard(ctx, "add_admins")
    if g:
        return g
    ent = await hub.entity(ctx["chat"])
    rt = dict(DEFAULT_RIGHTS)
    rt.update(act.get("rights") or {})
    title = fmt(act.get("title") or "", ctx)[:16] or None
    await hub.client.edit_admin(
        ent, ctx["user"], is_admin=True, title=title,
        change_info=bool(rt["change_info"]), delete_messages=bool(rt["delete_messages"]),
        ban_users=bool(rt["ban_users"]), invite_users=bool(rt["invite_users"]),
        pin_messages=bool(rt["pin_messages"]), add_admins=bool(rt["add_admins"]),
        manage_call=bool(rt["manage_call"]), anonymous=bool(rt["anonymous"]))
    return ok("Admin banano hoyeche" + (f" ({title})" if title else ""),
              {"type": "demote", "chat": ctx["chat"], "user": ctx["user"]})


async def a_demote(act, ctx):
    g = await _guard(ctx, "add_admins")
    if g:
        return g
    ent = await hub.entity(ctx["chat"])
    await hub.client.edit_admin(
        ent, ctx["user"], is_admin=False, change_info=False, delete_messages=False,
        ban_users=False, invite_users=False, pin_messages=False, add_admins=False,
        manage_call=False, anonymous=False)
    return ok("Admin theke namano hoyeche")


async def a_add_to_group(act, ctx):
    if not ctx.get("user"):
        return fail("Target user paoa jayni")
    try:
        target_id = int(act.get("target_group"))
    except Exception:
        return fail("Kon group e add korbo ta set kora nai")
    tgt = await hub.entity(target_id)
    if await hub.has_right(tgt, "invite_users") is False:
        return fail("Oi group e tomar invite korar adhikar nei")
    try:
        if isinstance(tgt, types.Channel):
            await hub.client(functions.channels.InviteToChannelRequest(tgt, [ctx["user"]]))
        else:
            await hub.client(functions.messages.AddChatUserRequest(chat_id=tgt.id, user_id=ctx["user"], fwd_limit=50))
        return ok("Group e add kora hoyeche: " + getattr(tgt, "title", str(target_id)))
    except Exception as e:
        if type(e).__name__ not in ("UserPrivacyRestrictedError", "UserNotMutualContactError",
                                    "UserChannelsTooMuchError", "UserKickedError"):
            raise
        # privacy: invite link pathai
        res = await hub.client(functions.messages.ExportChatInviteRequest(peer=tgt))
        text = fmt(act.get("text") or "Ei group e join koro: {link}", ctx).replace("{link}", res.link)
        await hub.client.send_message(ctx["user"], text)
        return ok("Privacy er karone add hoyni, DM e invite link pathiyechi")


async def a_dm(act, ctx):
    if not ctx.get("user"):
        return fail("Target user paoa jayni")
    text = fmt(act.get("text") or "Hi {name}", ctx)
    await hub.client.send_message(ctx["user"], text)
    return ok("DM pathano hoyeche")


async def a_reply(act, ctx):
    ent = await hub.entity(ctx["chat"])
    text = fmt(act.get("text") or "OK", ctx)
    await hub.client.send_message(ent, text, reply_to=ctx.get("msg_id"))
    return ok("Group e message pathano hoyeche")


async def a_pin(act, ctx):
    if not ctx.get("msg_id"):
        return fail("Kon message pin korbo? (message e reply dao)")
    ent = await hub.entity(ctx["chat"])
    if await hub.has_right(ent, "pin_messages") is False:
        return fail("Ei group e tomar pin korar adhikar nei")
    await hub.client.pin_message(ent, ctx["msg_id"])
    return ok("Pin kora hoyeche")


async def a_unpin(act, ctx):
    ent = await hub.entity(ctx["chat"])
    await hub.client.unpin_message(ent, ctx.get("msg_id"))
    return ok("Unpin kora hoyeche")


HANDLERS = {
    "ban": a_ban, "mute": a_mute, "unban": a_unban, "unmute": a_unmute, "kick": a_kick,
    "warn": a_warn, "unwarn": a_unwarn, "delete": a_delete, "delete_all": a_delete_all,
    "promote": a_promote, "demote": a_demote, "add_to_group": a_add_to_group,
    "dm": a_dm, "reply": a_reply, "pin": a_pin, "unpin": a_unpin,
}

ACTION_TYPES = list(HANDLERS.keys())


async def run(act, ctx):
    fn = HANDLERS.get(act.get("type"))
    if not fn:
        return fail("Ochena action: " + str(act.get("type")))
    try:
        try:
            return await fn(act, ctx)
        except FLOOD as e:
            await asyncio.sleep(min(flood_secs(e), 120) + 1)
            return await fn(act, ctx)
    except Exception as e:
        return fail(readable(e))


async def undo(entry):
    u = entry.get("undo")
    if not u:
        return fail("Eta undo kora jay na")
    ctx = {"chat": u["chat"], "user": u["user"], "by": hub.me_id}
    await hub.fill_names(ctx)
    return await run({"type": u["type"]}, ctx)
