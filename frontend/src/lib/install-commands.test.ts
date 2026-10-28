import { describe, expect, it } from "vitest";
import { installCommands } from "@/lib/install-commands";

describe("installCommands", () => {
  it("fills the address and token into both commands", () => {
    const c = installCommands("https://mallt.example.com/", "0192.abc-DEF_1");
    expect(c?.windows).toBe("powershell -ExecutionPolicy Bypass -File install.ps1 -Url https://mallt.example.com -Token 0192.abc-DEF_1");
    expect(c?.linux).toBe("sudo bash install.sh --url https://mallt.example.com --token 0192.abc-DEF_1");
  });
  it("refuses anything that could be interpreted by a shell", () => {
    for (const bad of ["a b", "a;rm -rf /", "a$(x)", "a`x`", "a\nb", ""]) {
      expect(installCommands("https://x.test", bad)).toBeNull();
    }
    expect(installCommands("https://x.test/; evil", "abc")).toBeNull();
    expect(installCommands("javascript:alert(1)", "abc")).toBeNull();
  });
});
