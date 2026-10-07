"""plugins/botui.py - bot er bortone (confirm) ar captcha"""
import time

import actions
import engine
from core import Button, display_name, events, hub
from plugins import welcome


def attach_bot(hub_, bot):
    bot.add_event_handler(_start, events.NewMessage(pattern=r"^/start"))
    bot.add_event_handler(_callback, events.CallbackQuery())
    bot.add_event_handler(_bot_join, events.ChatAction())


async def _start(event):
    if event.is_private:
        mine = event.sender_id == hub.me_id
        await event.respond("Ami tomar moderation bot. Confirm er bortone ekhane ashbe." if mine
                            else "Ei bot ta shudhu group moderator er jonno.")


async def _callback(event):
    try:
        data = (event.data or b"").decode()
        if data.startswith("cf:"):
            if event.sender_id != hub.me_id:
                await event.answer("Eta tomar jonno na", alert=True)
                return
            _, cid, yes = data.split(":")
            found = await engine.resolve_confirm(cid, yes == "1")
            await event.answer("Hoyeche" if found and yes == "1" else ("Bondho" if found else "Somoy shesh"))
            try:
                await event.edit(("✅ Kora hoyeche" if yes == "1" else "❌ Bondho") if found else "⌛ Somoy shesh")
            except Exception:
                pass
        elif data.startswith("cap:"):
            _, chat, uid = data.split(":")
            chat, uid = int(chat), int(uid)
            if event.sender_id != uid:
                await event.answer("Eta tomar jonno na", alert=True)
                return
            hub.captcha.pop(f"{chat}:{uid}", None)
            hub.save_captcha()
            ctx = {"chat": chat, "user": uid, "by": hub.me_id}
            await hub.fill_names(ctx)
            res = await actions.run({"type": "unmute"}, ctx)
            hub.log(kind="action", rule="captcha", action="verified", chat=chat, chat_title=ctx.get("chat_title", ""),
                    user=uid, user_name=ctx.get("user_name", ""), by=hub.me_id, ok=res["ok"],
                    msg="Captcha pass: " + res["msg"], undo=None)
            await event.answer("✅ Verified")
            try:
                await event.delete()
            except Exception:
                pass
            try:
                user = await hub.entity(uid)
                await welcome.send_welcome(chat, user)
            except Exception:
                pass
    except Exception as e:
        hub.log(kind="error", msg=f"bot callback: {type(e).__name__}: {e}")


async def _bot_join(event):
    try:
        if not (event.user_joined or event.user_added):
            return
        chat_id = event.chat_id
        gc = hub.group_cfg(chat_id)
        c = gc["captcha"]
        if not (gc["enabled"] and c["on"] and hub.client):
            return
        for u in (await event.get_users()) or []:
            if getattr(u, "bot", False) or u.id == hub.me_id:
                continue
            ctx = {"chat": chat_id, "user": u.id, "by": hub.me_id, "user_name": display_name(u)}
            await hub.fill_names(ctx)
            res = await actions.run({"type": "mute", "duration_min": 0}, ctx)
            if not res["ok"]:
                hub.log(kind="error", msg="Captcha: mute kora jayni: " + res["msg"])
                continue
            text = actions.fmt(c["text"], ctx)
            m = await hub.bot.send_message(
                chat_id, text, buttons=[[Button.inline("✅ Ami manush", f"cap:{chat_id}:{u.id}".encode())]])
            hub.captcha[f"{chat_id}:{u.id}"] = {
                "chat": chat_id, "user": u.id, "msg": m.id,
                "deadline": time.time() + int(c["timeout_min"]) * 60}
            hub.save_captcha()
    except Exception as e:
        hub.log(kind="error", msg=f"captcha join: {type(e).__name__}: {e}")
