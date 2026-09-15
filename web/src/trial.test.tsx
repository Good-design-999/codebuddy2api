import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vite-plus/test";
import { Trial } from "./Trial";
import { Credentials } from "./pages/Credentials";
import { api, useResource } from "./api";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  useResource: vi.fn(),
}));
beforeEach(() => vi.restoreAllMocks());
const available = { ok: false, can_claim: true, state: "available", message: "可手动申请" };
const credential = {
  id: "intl",
  name: "intl.info",
  enabled: true,
  profile: "intl-work",
  trial_supported: true,
  trial: available,
};
function mount() {
  const onClose = vi.fn();
  const onDone = vi.fn();
  const view = render(<Trial credential={credential} onClose={onClose} onDone={onDone} />);
  return { ...view, onClose, onDone };
}
it("only opens a confirmation drawer for supported accounts and sends no claim on open", async () => {
  vi.mocked(useResource).mockReturnValue({
    data: [credential, { id: "cn", name: "cn.info", enabled: true, trial_supported: false }],
    loading: false,
    error: null,
    reload: vi.fn(),
  });
  const post = vi.spyOn(api, "post");
  render(<Credentials />);
  expect(screen.queryByRole("button", { name: "领取体验积分 cn.info" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "领取体验积分 intl.info" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getByRole("button", { name: "确认领取" })).toHaveProperty("disabled", false);
  expect(post).not.toHaveBeenCalled();
});
it("submits one account once and reports successful persisted completion", async () => {
  let finish!: (value: unknown) => void;
  const post = vi.spyOn(api, "post").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { onDone, onClose } = mount();
  fireEvent.click(screen.getByRole("button", { name: "确认领取" }));
  fireEvent.click(screen.getByRole("button", { name: "确认领取" }));
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith(
    "/credentials/intl/trial",
    undefined,
    expect.objectContaining({ timeout: 45000 }),
  );
  expect(screen.getByRole("button", { name: "关闭抽屉" })).toHaveProperty("disabled", true);
  expect(onClose).not.toHaveBeenCalled();
  await act(async () =>
    finish({
      data: {
        results: [
          {
            id: "intl",
            ok: true,
            can_claim: false,
            state: "claimed",
            message: "领取成功，请同步余额",
          },
        ],
      },
    }),
  );
  expect(screen.getByText("已领取")).toBeTruthy();
  expect(screen.getByRole("button", { name: "确认领取" })).toHaveProperty("disabled", true);
  expect(onDone).toHaveBeenCalledTimes(1);
});
it("shows safe timeout details inside the drawer and refreshes without claiming again", async () => {
  const state = {
    ok: false,
    can_claim: false,
    state: "timeout",
    message: "领取请求超时，官方可能已处理",
    status: null,
    code: null,
    retry_at: 2000000000,
  };
  const post = vi
    .spyOn(api, "post")
    .mockResolvedValue({ data: { results: [{ id: "intl", ...state }] } });
  const get = vi
    .spyOn(api, "get")
    .mockResolvedValue({ data: { credentials: [{ ...credential, trial: state }] } });
  mount();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "确认领取" })));
  expect(screen.getByRole("alert").textContent).toContain("领取请求超时");
  expect(screen.getByText(/最早可再次手动申请/)).toBeTruthy();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "刷新领取状态" })));
  expect(get).toHaveBeenCalledWith("/credentials", expect.any(Object));
  expect(post).toHaveBeenCalledTimes(1);
});
it("reports partial upstream completion when ledger persistence failed", async () => {
  vi.spyOn(api, "post").mockResolvedValue({
    data: {
      results: [
        {
          id: "intl",
          ok: false,
          can_claim: false,
          state: "storage_error",
          message: "领取记录保存失败，请先核对余额",
          claimed: true,
        },
      ],
    },
  });
  mount();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "确认领取" })));
  expect(screen.getByText("官方已确认，记录未保存")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("保存失败");
});
it("does not retry a lost HTTP response or accept another account's result", async () => {
  const post = vi.spyOn(api, "post").mockRejectedValue(new Error("network timeout"));
  vi.spyOn(api, "get").mockResolvedValue({ data: { credentials: [credential] } });
  mount();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "确认领取" })));
  expect(screen.getByRole("alert").textContent).toContain("请求失败不代表后台已停止");
  expect(screen.getByRole("button", { name: "确认领取" })).toHaveProperty("disabled", true);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "刷新领取状态" })));
  post.mockResolvedValueOnce({ data: { results: [{ id: "wrong-account", ...available }] } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "确认领取" })));
  expect(screen.getByRole("alert").textContent).toContain("领取账号或结果未确认");
});
it("ignores late responses after unmount and aborts the browser request", async () => {
  let finish!: (value: unknown) => void;
  const post = vi.spyOn(api, "post").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { unmount, onDone } = mount();
  fireEvent.click(screen.getByRole("button", { name: "确认领取" }));
  const signal = post.mock.calls[0][2]?.signal;
  unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => finish({ data: { results: [{ id: "intl", ...available }] } }));
  expect(onDone).not.toHaveBeenCalled();
});
