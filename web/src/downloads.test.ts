import { describe, expect, it } from "vite-plus/test";
import { downloadFilename } from "./downloads";

const fallback = "credential.info";
const unicode = "测试 账号.info";
const encoded = encodeURIComponent(unicode);

describe("credential attachment filenames", () => {
  it.each([
    [`attachment; filename*=UTF-8''${encoded}`, unicode],
    [`attachment; filename=legacy.info; filename*=utf-8'zh-CN'${encoded}`, unicode],
    [`attachment; FILENAME*=uTf-8''${encoded}; filename=legacy.info`, unicode],
    ['attachment; filename="account; one.info"', "account; one.info"],
    ['attachment; filename="account\\;one.info"', "account;one.info"],
    ['attachment; description="ignore; filename=fake.info"; filename=real.info', "real.info"],
    ['attachment; filename="account%20one.info"', "account%20one.info"],
    ["attachment; filename= account one.info  ", "account one.info"],
    ["attachment; filename*=UTF-8''account+one.info", "account+one.info"],
  ])("reads %s", (header, expected) => {
    expect(downloadFilename(header!, fallback)).toBe(expected);
  });

  it.each([
    "utf-8''%ZZ",
    "utf-8''%FF.info",
    "utf-8''%E4%BD",
    "iso-8859-1''caf%E9.info",
    "utf-8''",
    "utf-8''%2e%2e%2fsecret.info",
    "utf-8''folder%5csecret.info",
    "utf-8''account%00.info",
    "utf-8''account.info%0A",
  ])("uses the safe legacy filename when extended value %s is invalid", (value) => {
    expect(
      downloadFilename(`attachment; filename*= ${value}; filename=legacy.info`, fallback),
    ).toBe("legacy.info");
  });

  it.each([
    "",
    "attachment",
    'attachment; filename=""',
    "attachment; filename=../secret.info",
    "attachment; filename=folder\\secret.info",
    "attachment; filename=C:secret.info",
    'attachment; filename="account\0.info"',
    'attachment; filename="account\u007f.info"',
    'attachment; filename=".."',
    "attachment; filename*=UTF-8''%2fsecret.info",
    "attachment; filename=one.info; filename=two.info",
    "attachment; filename*=UTF-8''one.info; filename*=UTF-8''two.info",
    'attachment; description="ignore; filename=fake.info"',
    "attachment; x-filename=fake.info",
    "attachment; filename=one.info\r\nfilename=two.info",
    `attachment; filename=${"a".repeat(260)}.info`,
    `attachment; description=${"a".repeat(8192)}`,
  ])("uses a safe default for %s", (header) => {
    expect(downloadFilename(header, fallback)).toBe(fallback);
    expect(downloadFilename(header, "credentials.zip")).toBe("credentials.zip");
  });

  it("ignores duplicate extended parameters without losing an unambiguous legacy name", () => {
    expect(
      downloadFilename(
        "attachment; filename=legacy.info; filename*=UTF-8''one.info; filename*=UTF-8''two.info",
        fallback,
      ),
    ).toBe("legacy.info");
  });
});
