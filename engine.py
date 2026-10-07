"""engine.py - rule khuje ber kora, confirm/undo/dry-run, action chalano"""
import asyncio
import time
import uuid

import actions
from core import Button, hub, norm_emoji


def _chat_ok(rule, chat_id):
    gs = [str(x) for x in (rule.get("groups") or ["*"])]
    return "*" in gs or str(chat_id) in gs


def find_rules(ttype, key, chat_id):
    out = []
    for r in hub.cfg["rules"]:
        if not r.get("enabled", True):
            continue
        t = r.get("trigger") or {}
        if t.get("type") != ttype:
            continue
        if ttype == "reaction":
            if norm_emoji(t.get("emoji", "")) != norm_emoji(key):
                continue
        elif ttype == "command":
            if (t.get("name", "") or "").lower().lstrip(".") != (key or "").lower():
                continue
        if not _chat_ok(r, chat_id):
            continue
        out.append(r)
    return out


def has_reaction_rules(chat_id):
    return any(r.get("enabled", True) and (r.get("trigger") or {}).get("type") == "reaction"
               and _chat_ok(r, chat_id) for r in hub.cfg["rules"])


def trusted_entry(uid):
    for t in hub.cfg["trusted"]:
        try:
            if int(t["id"]) == uid:
                return t
        except Exception:
            pass
    return None


def allowed(rule, by_id):
    if by_id == hub.me_id:
        return True
    if rule.get("who", "me") != "trusted":
        return False
    t = trusted_entry(by_id)
    if not t:
        return False
    perms = t.get("perms") or []
    if "*" in perms:
        return True
    return all(a.get("type") in perms for a in rule.get("actions", []))


def fire(ttype, key, chat_id, target_id, by_id, msg=None, args=None, still_valid=None):
    """Jotogulo rule match korlo toto gulo chalu kore, sonkhya ferot dey"""
    args = args or {}
    n = 0
    for rule in find_rules(ttype, key, chat_id):
        if not allowed(rule, by_id):
            continue
        ctx = {
            "chat": chat_id, "user": target_id, "by": by_id,
            "msg_id": getattr(msg, "id", None), "msg_out": bool(getattr(msg, "out", False)),
            "duration_min": args.get("duration_min"), "text": args.get("text", ""),
        }
        n += 1
        asyncio.create_task(_process(rule, ctx, still_valid))
    return n


async def _process(rule, ctx, still_valid):
    try:
        await hub.fill_names(ctx)
        st = hub.cfg["settings"]
        summary = (f"{rule.get('name', 'rule')}: {ctx['user_name'] or ctx['user']} @ "
                   f"{ctx['chat_title']} -> " + ", ".join(a.get("type", "?") for a in rule.get("actions", [])))
        wait = int(st.get("undo_seconds", 0) or 0)
        if still_valid and wait > 0:
            await asyncio.sleep(wait)
            if not await still_valid():
                hub.log(kind="cancel", msg="Undo window e bondho: " + summary)
                return
        if st.get("dry_run"):
            hub.log(kind="dry", rule=rule.get("name"), chat=ctx["chat"], chat_title=ctx["chat_title"],
                    user=ctx["user"], user_name=ctx["user_name"], msg="Dry-run (kichu hoyni): " + summary)
            return
        if rule.get("confirm") or st.get("confirm_all"):
            await ask_confirm(rule, ctx, summary)
            return
        await execute(rule.get("actions", []), ctx, rule.get("name", "rule"))
    except Exception as e:
        hub.log(kind="error", msg=f"engine: {type(e).__name__}: {e}")


async def execute(acts, ctx, rule_name):
    for act in acts:
        if not hub.rate_ok():
            hub.log(kind="limit", msg="Rate limit: onek beshi action, baki gulo thamano hoyeche")
            return
        res = await actions.run(act, ctx)
        hub.log(kind="action", rule=rule_name, action=act.get("type"), chat=ctx["chat"],
                chat_title=ctx.get("chat_title", ""), user=ctx.get("user"),
                user_name=ctx.get("user_name", ""), by=ctx.get("by"), ok=res["ok"],
                msg=res["msg"], undo=res["undo"])
        if not res["ok"] and not act.get("optional"):
            break


async def run_now(acts, ctx, rule_name):
    """Website theke / automod theke sorasori (rule charai)"""
    await hub.fill_names(ctx)
    st = hub.cfg["settings"]
    if st.get("dry_run"):
        hub.log(kind="dry", rule=rule_name, chat=ctx["chat"], chat_title=ctx["chat_title"], user=ctx.get("user"),
                user_name=ctx["user_name"], msg="Dry-run (kichu hoyni): " + ", ".join(a["type"] for a in acts))
        return
    await execute(acts, ctx, rule_name)


# ---------- confirm ----------
async def ask_confirm(rule, ctx, summary):
    cid = uuid.uuid4().hex[:8]
    hub.pending[cid] = {"id": cid, "t": time.time(), "summary": summary, "rule": rule, "ctx": ctx}
    buttons = [[Button.inline("✅ Hobe", f"cf:{cid}:1".encode()), Button.inline("❌ Na", f"cf:{cid}:0".encode())]]
    await hub.notify_owner("Confirm lagbe:\n" + summary, buttons=buttons)
    asyncio.create_task(_expire(cid))


async def resolve_confirm(cid, yes):
    p = hub.pending.pop(cid, None)
    if not p:
        return False
    if yes:
        await execute(p["rule"].get("actions", []), p["ctx"], p["rule"].get("name", "rule"))
    else:
        hub.log(kind="cancel", msg="Confirm e 'Na' bola hoyeche: " + p["summary"])
    return True


async def _expire(cid, secs=180):
    await asyncio.sleep(secs)
    if hub.pending.pop(cid, None):
        hub.log(kind="cancel", msg="Confirm er somoy shesh, kichu hoyni")
