"""plugins/welcome.py - welcome message + captcha (captcha er jonno bot lagbe)"""
import asyncio
import time

import actions
from core import events, hub


def attach(hub_, client):
    client.add_event_handler(_on_join, events.ChatAction())


async def send_welcome(chat_id, user):
    w = hub.group_cfg(chat_id)["welcome"]
    if not w["on"]:
        return
    ctx = {"user_name": hub_name(user), "user": user.id, "chat_title": ""}
    try:
        ent = await hub.entity(chat_id)
        ctx["chat_title"] = getattr(ent, "title", "")
        m = await hub.client.send_message(ent, actions.fmt(w["text"], ctx))
        if int(w.get("delete_after", 0)) > 0:
            asyncio.create_task(_del_later(ent, m.id, int(w["delete_after"])))
    except Exception as e:
        hub.log(kind="error", msg=f"welcome: {type(e).__name__}: {e}")


def hub_name(u):
    from core import display_name
    return display_name(u)


async def _del_later(ent, mid, secs):
    await asyncio.sleep(secs)
    try:
        await hub.client.delete_messages(ent, [mid])
    except Exception:
        pass


async def _on_join(event):
    try:
        if not (event.user_joined or event.user_added):
            return
        chat_id = event.chat_id
        gc = hub.group_cfg(chat_id)
        if not gc["enabled"]:
            return
        if gc["captcha"]["on"] and hub.bot:
            return  # bot captcha dekhabe, verify holei welcome jabe
        if not gc["welcome"]["on"]:
            return
        for u in (await event.get_users()) or []:
            if getattr(u, "bot", False) or u.id == hub.me_id:
                continue
            await send_welcome(chat_id, u)
    except Exception as e:
        hub.log(kind="error", msg=f"join: {type(e).__name__}: {e}")


async def background(hub_):
    """Captcha er somoy shesh hole fail action"""
    while True:
        await asyncio.sleep(20)
        try:
            now = time.time()
            for key, c in list(hub.captcha.items()):
                if c["deadline"] > now:
                    continue
                hub.captcha.pop(key, None)
                hub.save_captcha()
                if not hub.client:
                    continue
                fail = hub.group_cfg(c["chat"])["captcha"].get("fail", "kick")
                ctx = {"chat": c["chat"], "user": c["user"], "by": hub.me_id}
                await hub.fill_names(ctx)
                res = await actions.run({"type": "ban" if fail == "ban" else "kick", "duration_min": 0}, ctx)
                hub.log(kind="action", rule="captcha", action=fail, chat=c["chat"],
                        chat_title=ctx.get("chat_title", ""), user=c["user"], user_name=ctx.get("user_name", ""),
                        by=hub.me_id, ok=res["ok"], msg="Captcha fail: " + res["msg"], undo=res["undo"])
                if hub.bot and c.get("msg"):
                    try:
                        await hub.bot.delete_messages(c["chat"], [c["msg"]])
                    except Exception:
                        pass
        except Exception as e:
            hub.log(kind="error", msg=f"captcha sweep: {e}")
