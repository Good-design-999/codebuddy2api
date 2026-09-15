"""Safe manual trial results over the existing per-account ledger."""
import time

from . import model_policy, trial_rewards

_MESSAGES = {
    "available": "尚未领取，可手动向官方申请一次性体验积分",
    "claimed": "体验积分已领取，可另行同步余额",
    "already": "官方确认该账号已领取，无需重复申请",
    "unconfirmed": "上次领取结果尚未确认，可能仍在执行；请勿立即重复申请",
    "timeout": "领取请求超时，官方可能已处理；请先核对余额，勿重复点击",
    "network_error": "连接官方失败或响应中断，请检查服务器网络、DNS 和代理；勿立即重复申请",
    "invalid_response": "官方响应格式无效，未确认领取成功",
    "response_too_large": "官方响应超过安全大小限制，已停止读取，未确认领取成功",
    "auth_error": "官方拒绝了当前凭证，请刷新 Token 或重新登录后核对",
    "credential_error": "凭证不可用或 Token 刷新失败，未发送领取请求；请先刷新凭证或重新登录",
    "rejected": "官方未确认领取成功，资格和额度由官方决定",
    "storage_error": "领取记录无法读取或保存，已停止操作；请检查凭证目录权限和磁盘空间",
    "changed": "凭证身份、代次或启用状态已变化，已停止后续操作，请刷新列表核对",
    "not_applicable": "仅支持国际 WorkBuddy 账号，国内账号及国际 CodeBuddy 不适用",
    "internal_error": "领取操作异常，结果未确认；请先核对余额及领取记录，勿重复点击",
}


def failure(state, **fields):
    return {"ok": False, "can_claim": False, "state": state, "message": _MESSAGES[state], **fields}


def view(record=None, *, now=None):
    now = time.time() if now is None else now
    record = record or {}
    attempted = record.get("attempted_at")
    retry_at = attempted + trial_rewards.RETRY_INTERVAL if attempted is not None else None
    status, code = record.get("status"), record.get("code")
    if record.get("ok") is True:
        state = "claimed"
    elif record.get("already") is True:
        state = "already"
    elif attempted is None:
        state = "available"
    elif record.get("finished_at") is None:
        state = "unconfirmed"
    elif status is None:
        state = "network_error"
    elif status in (401, 403):
        state = "auth_error"
    else:
        state = "rejected"
    done = state in {"claimed", "already"}
    return {"ok": done, "can_claim": not done and (retry_at is None or now >= retry_at),
            "state": state, "message": _MESSAGES[state], "code": code, "status": status,
            "attempted_at": attempted, "finished_at": record.get("finished_at"),
            "retry_at": None if done else retry_at}


def inventory(ledger):
    if ledger is None:
        return None
    try:
        return ledger.snapshot()
    except (OSError, ValueError):
        return None


def perform(gateway, pool, entry):
    """Called only by a single-account admin POST under the maintenance lock."""
    if entry.get("profile") != "intl-work":
        return failure("not_applicable", skipped=True)
    ledger = gateway.CONFIG.get("trial_ledger")
    records = inventory(ledger)
    if records is None:
        return failure("storage_error")
    key, cm = entry.get("account_key"), entry["cm"]
    previous = view(records.get(key))
    if not previous["can_claim"]:
        return {**previous, "skipped": True}
    try:
        with cm._lock:
            if cm.summary().get("account_key") != key:
                return failure("changed")
            try:
                headers = cm.get_headers()
            except Exception:
                return failure("credential_error")
            generation = cm._generation
        profile = gateway.profile_for_headers(headers)
        uid = headers.get("X-User-Id")
        if (profile != "intl-work" or not uid or
                gateway.account_key(profile, uid, headers.get("X-Enterprise-Id", "")) != key):
            return failure("changed")

        def current():
            return (model_policy.credential_enabled(gateway.CONFIG, entry)
                    and pool.apply_if_current(cm, generation, lambda: None))

        result = trial_rewards.attempt_trial(ledger, key, headers, can_claim=current)
        # Retain the original account's result even if the token was replaced mid-flight.
        records = inventory(ledger)
        if records is None:
            return failure("storage_error", claimed=result.get("ok") is True,
                           upstream_already=result.get("already") is True)
        status = view(records.get(key))
        if result.get("error") in _MESSAGES and result.get("status") not in (401, 403):
            status.update(ok=False, can_claim=False, state=result["error"], message=_MESSAGES[result["error"]])
        if not current():
            status["message"] += "；凭证已变化，请刷新列表核对原账号"
        return status
    except trial_rewards.TrialSaveError as error:
        return failure("storage_error", claimed=error.result["ok"], upstream_already=error.result["already"],
                       message="官方请求已结束，但领取记录保存失败；请先核对余额，不要删除记录或立即重试")
    except (OSError, ValueError):
        return failure("storage_error")
    except Exception:
        return failure("internal_error")
