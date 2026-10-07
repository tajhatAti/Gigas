"""webapp.py - website er API"""
import time

from aiohttp import web

import actions
import engine
from core import (ALLOWED_REACTIONS, CRYPTG, CRYPTG_ERR, DEFAULT_GROUP, DEFAULT_SETTINGS,
                  deep_merge, display_name, hub)
from ui import HTML

MASK = "•••"


def J(d):
    return web.json_response(d)


async def body(req):
    try:
        return await req.json()
    except Exception:
        return {}


def public_settings():
    s = dict(hub.cfg["settings"])
    s["bot_token"] = MASK if s.get("bot_token") else ""
    return s


async def index(req):
    return web.Response(text=HTML, content_type="text/html")


async def api_state(req):
    return J({
        "status": hub.status, "error": hub.error, "me": hub.me_name, "me_id": hub.me_id,
        "bot": hub.bot_status, "started": hub.started, "now": time.time(),
        "settings": public_settings(), "rules": hub.cfg["rules"],
        "trusted": hub.cfg["trusted"], "protected": hub.cfg["protected"],
        "pending": [{k: p[k] for k in ("id", "t", "summary")} for p in hub.pending.values()],
        "logs": list(hub.logs)[:150], "react_debug": list(hub.react_debug),
        "cryptg": CRYPTG, "cryptg_err": CRYPTG_ERR, "reactions": ALLOWED_REACTIONS,
        "action_types": actions.ACTION_TYPES, "captcha_pending": len(hub.captcha),
    })


async def api_connect(req):
    s = ((await body(req)).get("session") or "").strip()
    if not s:
        return J({"ok": False, "error": "Session string dao"})
    ok = await hub.connect(s)
    return J({"ok": ok, "error": hub.error})


async def api_logout(req):
    await hub.logout()
    return J({"ok": True})


async def api_groups(req):
    if not hub.client:
        return J({"ok": False, "error": "Age session connect koro", "groups": []})
    try:
        groups = await hub.list_groups(force=req.query.get("force") == "1")
    except Exception as e:
        return J({"ok": False, "error": f"{type(e).__name__}: {e}", "groups": []})
    out = []
    for g in groups:
        g = dict(g)
        g["cfg"] = hub.group_cfg(g["id"])
        out.append(g)
    return J({"ok": True, "groups": out})


def _clean_list(v):
    return [str(x).strip() for x in (v or []) if str(x).strip()]


async def api_group_save(req):
    b = await body(req)
    try:
        chat = str(int(b.get("chat")))
    except Exception:
        return J({"ok": False, "error": "chat id thik na"})
    cfg = deep_merge(DEFAULT_GROUP, b.get("cfg") or {})
    cfg["automod"]["links"]["allow"] = _clean_list(cfg["automod"]["links"]["allow"])
    cfg["automod"]["words"]["list"] = _clean_list(cfg["automod"]["words"]["list"])
    for k in ("count", "seconds", "mute_min"):
        cfg["automod"]["flood"][k] = max(1, int(cfg["automod"]["flood"].get(k) or 1))
    cfg["captcha"]["timeout_min"] = max(1, int(cfg["captcha"].get("timeout_min") or 5))
    cfg["welcome"]["delete_after"] = max(0, int(cfg["welcome"].get("delete_after") or 0))
    hub.cfg["groups"][chat] = cfg
    hub.save()
    return J({"ok": True})


async def api_members(req):
    if not hub.client:
        return J({"ok": False, "error": "Age session connect koro", "members": []})
    try:
        chat = int(req.query.get("chat"))
        ent = await hub.entity(chat)
        out = []
        async for u in hub.client.iter_participants(ent, search=req.query.get("q", ""), limit=60):
            p = type(getattr(u, "participant", None)).__name__
            out.append({
                "id": u.id, "name": display_name(u), "username": getattr(u, "username", None),
                "bot": bool(getattr(u, "bot", False)),
                "admin": ("Admin" in p or "Creator" in p),
                "warns": hub.warn_get(chat, u.id),
            })
        return J({"ok": True, "members": out})
    except Exception as e:
        return J({"ok": False, "error": f"{type(e).__name__}: {e}", "members": []})


async def api_do(req):
    b = await body(req)
    act = b.get("action") or {}
    if act.get("type") not in actions.ACTION_TYPES:
        return J({"ok": False, "msg": "Ochena action"})
    if not hub.client:
        return J({"ok": False, "msg": "Age session connect koro"})
    try:
        ctx = {"chat": int(b.get("chat")), "user": int(b.get("user") or 0) or None,
               "by": hub.me_id, "msg_id": None}
    except Exception:
        return J({"ok": False, "msg": "chat/user id thik na"})
    n_before = len(hub.logs)
    await engine.run_now([act], ctx, "website")
    last = hub.logs[0] if hub.logs else {}
    if hub.cfg["settings"].get("dry_run"):
        return J({"ok": True, "msg": "Dry-run: kichu hoyni"})
    return J({"ok": bool(last.get("ok")), "msg": last.get("msg", "")})


def clean_rule(r, i):
    t = r.get("trigger") or {}
    ttype = t.get("type") if t.get("type") in ("reaction", "command") else "reaction"
    trig = {"type": ttype}
    if ttype == "reaction":
        trig["emoji"] = str(t.get("emoji") or "")
    else:
        trig["name"] = str(t.get("name") or "").strip().lstrip(".").lower()
    acts = []
    for a in r.get("actions") or []:
        if a.get("type") not in actions.ACTION_TYPES:
            continue
        a = dict(a)
        if "duration_min" in a:
            a["duration_min"] = max(0, int(a.get("duration_min") or 0))
        acts.append(a)
    gs = [str(x) for x in (r.get("groups") or [])]
    return {
        "id": str(r.get("id") or f"r_{int(time.time())}_{i}"),
        "name": str(r.get("name") or "Rule")[:60], "enabled": bool(r.get("enabled", True)),
        "trigger": trig, "who": r.get("who") if r.get("who") in ("me", "trusted") else "me",
        "groups": gs, "confirm": bool(r.get("confirm")), "actions": acts,
    }


async def api_rules_save(req):
    rules = (await body(req)).get("rules")
    if not isinstance(rules, list):
        return J({"ok": False, "error": "rules list lagbe"})
    try:
        hub.cfg["rules"] = [clean_rule(r, i) for i, r in enumerate(rules)]
    except Exception as e:
        return J({"ok": False, "error": f"{type(e).__name__}: {e}"})
    hub.save()
    return J({"ok": True, "rules": hub.cfg["rules"]})


async def api_settings_save(req):
    inc = (await body(req)).get("settings") or {}
    cur = hub.cfg["settings"]
    old_tok = cur.get("bot_token", "")
    for k, dv in DEFAULT_SETTINGS.items():
        if k not in inc:
            continue
        v = inc[k]
        try:
            if k == "bot_token":
                if v == MASK:
                    continue
                cur[k] = str(v).strip()
            elif isinstance(dv, bool):
                cur[k] = bool(v)
            elif isinstance(dv, int):
                cur[k] = max(0, int(v))
            else:
                cur[k] = str(v)
        except Exception:
            pass
    if cur.get("warn_action") not in ("mute", "ban", "kick"):
        cur["warn_action"] = "mute"
    if not cur.get("prefix"):
        cur["prefix"] = "."
    hub.save()
    if cur.get("bot_token", "") != old_tok and hub.client:
        await hub.connect_bot()
    return J({"ok": True, "bot": hub.bot_status})


async def api_lists_save(req):
    b = await body(req)
    trusted = []
    for t in b.get("trusted") or []:
        try:
            trusted.append({"id": int(t["id"]), "name": str(t.get("name") or "")[:40],
                            "perms": [str(p) for p in (t.get("perms") or [])]})
        except Exception:
            pass
    prot = []
    for x in b.get("protected") or []:
        try:
            prot.append(int(x))
        except Exception:
            pass
    hub.cfg["trusted"], hub.cfg["protected"] = trusted, prot
    hub.save()
    return J({"ok": True})


async def api_undo(req):
    lid = (await body(req)).get("id")
    entry = next((e for e in hub.logs if e.get("id") == lid), None)
    if not entry or not entry.get("undo"):
        return J({"ok": False, "msg": "Undo kora jabe na"})
    res = await actions.undo(entry)
    if res["ok"]:
        entry["undo"] = None
    hub.log(kind="action", rule="undo", action="undo", chat=entry.get("chat"),
            chat_title=entry.get("chat_title", ""), user=entry.get("user"),
            user_name=entry.get("user_name", ""), by=hub.me_id, ok=res["ok"],
            msg="Undo: " + res["msg"], undo=None)
    return J(res)


async def api_confirm(req):
    b = await body(req)
    found = await engine.resolve_confirm(str(b.get("id")), bool(b.get("ok")))
    return J({"ok": found})


def make_app():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/groups", api_groups)
    app.router.add_get("/api/members", api_members)
    for path, fn in (("connect", api_connect), ("logout", api_logout), ("group_save", api_group_save),
                     ("do", api_do), ("rules_save", api_rules_save), ("settings_save", api_settings_save),
                     ("lists_save", api_lists_save), ("undo", api_undo), ("confirm", api_confirm)):
        app.router.add_post("/api/" + path, fn)
    return app
