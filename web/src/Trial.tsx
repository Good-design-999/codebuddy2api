import { useEffect, useRef, useState } from "react";
import { api, credentialResponse, errorMessage, list, object, type Credential } from "./api";
import { Badge, Drawer, ErrorNotice } from "./components";
import s from "./ui.module.scss";

type TrialResult = {
  ok: boolean;
  can_claim: boolean;
  state: string;
  message: string;
  status?: number | null;
  code?: number | null;
  retry_at?: number | null;
  claimed?: boolean;
  upstream_already?: boolean;
};
function result(value: unknown): TrialResult {
  const row = object(value, "体验积分结果");
  if (
    typeof row.ok !== "boolean" ||
    typeof row.can_claim !== "boolean" ||
    typeof row.state !== "string" ||
    typeof row.message !== "string"
  )
    throw new Error("领取结果不完整，请刷新状态核验，不要直接重复领取");
  for (const key of ["status", "code", "retry_at"])
    if (
      row[key] !== undefined &&
      row[key] !== null &&
      (typeof row[key] !== "number" || !Number.isFinite(row[key]))
    )
      throw new Error("领取结果格式无效，请刷新状态核验");
  return row as TrialResult;
}
const unknown: TrialResult = {
  ok: false,
  can_claim: false,
  state: "unknown",
  message: "请先刷新领取状态",
};
export function Trial({
  credential,
  onClose,
  onDone,
}: {
  credential: Credential;
  onClose: () => void;
  onDone: () => void;
}) {
  const [status, setStatus] = useState<TrialResult>(unknown);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"claim" | "status" | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    try {
      setStatus(result(credential.trial));
    } catch (error) {
      setError(errorMessage(error));
    }
    return () => controller.current?.abort();
  }, [credential]);
  const execute = async (claim: boolean) => {
    if (controller.current || (claim && !status.can_claim)) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(claim ? "claim" : "status");
    setError(null);
    if (claim) setStatus((old) => ({ ...old, can_claim: false }));
    try {
      if (claim) {
        const response = await api.post(
          `/credentials/${encodeURIComponent(credential.id)}/trial`,
          undefined,
          { signal: abort.signal, timeout: 45000 },
        );
        const rows = list(object(response.data).results, "领取操作结果");
        if (rows.length !== 1 || rows[0].id !== credential.id)
          throw new Error("领取账号或结果未确认，请刷新状态核验");
        if (!abort.signal.aborted) setStatus(result(rows[0]));
      } else {
        const response = await api.get("/credentials", { signal: abort.signal });
        const row = credentialResponse(response.data).find((row) => row.id === credential.id);
        if (!row || row.trial_supported !== true || row.enabled !== true)
          throw new Error("账号已变化、停用或不适用，请关闭后刷新凭证列表");
        if (!abort.signal.aborted) setStatus(result(row.trial));
      }
    } catch (error) {
      if (!abort.signal.aborted) {
        setStatus((old) => ({ ...old, can_claim: false }));
        setError(`${errorMessage(error)}；请求失败不代表后台已停止，请先刷新状态核验。`);
      }
    } finally {
      controller.current = null;
      if (!abort.signal.aborted) {
        setBusy(null);
        onDone();
      }
    }
  };
  const failed = !status.ok && !["available", "unknown"].includes(status.state);
  return (
    <Drawer title="领取一次性体验积分" onClose={onClose} dismissDisabled={busy !== null}>
      <p>
        <strong>{credential.name ?? credential.id}</strong> · 国际 WorkBuddy
      </p>
      <p className={s.note}>
        仅向官方申请当前账号的一次性体验积分，不签到、不旅行、不切换账号。资格和额度由官方决定。
      </p>
      <div role="status" aria-live="polite">
        <Badge tone={status.ok ? "good" : failed ? "warn" : "neutral"}>
          {status.claimed || status.upstream_already
            ? "官方已确认，记录未保存"
            : status.ok
              ? "已领取"
              : "未确认领取"}
        </Badge>
        {!failed && <p>{status.message}</p>}
        {busy && <p>{busy === "claim" ? "正在申请，请勿重复点击…" : "正在读取本地领取记录…"}</p>}
      </div>
      <ErrorNotice message={error ?? (failed ? status.message : null)} />
      {(status.status != null || status.code != null) && (
        <p className={s.note}>
          HTTP 状态：{status.status ?? "未收到"} · 官方业务码：{status.code ?? "未知"}
        </p>
      )}
      {!status.can_claim && status.retry_at != null && (
        <p className={s.note}>
          最早可再次手动申请：{new Date(status.retry_at * 1000).toLocaleString("zh-CN")}
        </p>
      )}
      <div className={s.actions}>
        <button
          className={s.primary}
          disabled={busy !== null || !status.can_claim || credential.enabled !== true}
          onClick={() => void execute(true)}
        >
          确认领取
        </button>
        <button disabled={busy !== null} onClick={() => void execute(false)}>
          刷新领取状态
        </button>
      </div>
      <p className={s.note}>
        刷新状态不会领取。失败至少等待 24
        小时；关闭页面不会撤销已发送请求。领取成功后可另行同步余额。
      </p>
    </Drawer>
  );
}
