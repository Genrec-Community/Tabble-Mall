import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import type { StaffMe } from "@/lib/api";
import { StaffSessionContext, type StaffSession } from "@/lib/auth/staff-session";
import { LoginForm } from "@/components/login-form";

const push = vi.fn();
const toastError = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: push }),
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("sonner", () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

const me = (over: Partial<StaffMe> = {}): StaffMe => ({
  id: "1",
  username: "asha",
  display_name: "Asha",
  must_change_password: false,
  totp_enabled: false,
  grants: [{ role_key: "org_owner", scope_type: "organization", organization_id: "o", mall_id: null, store_id: null, permissions: [] }],
  ...over,
});

function renderForm(login: StaffSession["login"]) {
  const session: StaffSession = {
    status: "anon",
    me: null,
    login,
    logout: vi.fn(),
    reload: vi.fn(),
    can: () => false,
  };
  render(
    <StaffSessionContext.Provider value={session}>
      <LoginForm />
    </StaffSessionContext.Provider>,
  );
}

beforeEach(() => {
  push.mockReset();
  toastError.mockReset();
  search = "";
});

describe("LoginForm", () => {
  it("signs in and sends the user to their own area", async () => {
    const login = vi.fn().mockResolvedValue(me());
    renderForm(login);
    await userEvent.type(screen.getByLabelText("Username"), "asha");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(login).toHaveBeenCalledWith("asha", "a-long-password", undefined);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/org"));
    expect(screen.queryByLabelText("Authenticator code")).toBeNull();
  });

  it("asks for the authenticator code when the server says it is required, then retries with it", async () => {
    const login = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(401, "totp_required", "Unauthorized", "Enter your authenticator code."))
      .mockResolvedValueOnce(me({ grants: [{ role_key: "platform_admin", scope_type: "platform", organization_id: null, mall_id: null, store_id: null, permissions: [] }] }));
    renderForm(login);
    await userEvent.type(screen.getByLabelText("Username"), "root");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const code = await screen.findByLabelText("Authenticator code");
    expect(toastError).not.toHaveBeenCalled(); // asking for a code is not an error
    await userEvent.type(code, "123456");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(login).toHaveBeenLastCalledWith("root", "a-long-password", "123456");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin"));
  });

  it("shows other failures as a message and stays on the page", async () => {
    const login = vi.fn().mockRejectedValue(new ApiError(401, "invalid_credentials", "Unauthorized", "Wrong username or password."));
    renderForm(login);
    await userEvent.type(screen.getByLabelText("Username"), "asha");
    await userEvent.type(screen.getByLabelText("Password"), "nope-nope-nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Wrong username or password."));
    expect(push).not.toHaveBeenCalled();
  });

  it("sends people with a temporary password to change it first", async () => {
    renderForm(vi.fn().mockResolvedValue(me({ must_change_password: true })));
    await userEvent.type(screen.getByLabelText("Username"), "asha");
    await userEvent.type(screen.getByLabelText("Password"), "temp-password-123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login/password"));
  });

  it("returns to the page they were trying to open, but only if it is a safe in-app path", async () => {
    search = "next=/org/123";
    renderForm(vi.fn().mockResolvedValue(me()));
    await userEvent.type(screen.getByLabelText("Username"), "asha");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/org/123"));
  });

  it("ignores an unsafe next parameter", async () => {
    search = "next=https://evil.test";
    renderForm(vi.fn().mockResolvedValue(me()));
    await userEvent.type(screen.getByLabelText("Username"), "asha");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/org"));
  });

  it("disables the button while signing in so a double click cannot submit twice", async () => {
    let resolve!: (m: StaffMe) => void;
    const login = vi.fn().mockReturnValue(new Promise<StaffMe>((r) => (resolve = r)));
    renderForm(login);
    await userEvent.type(screen.getByLabelText("Username"), "asha");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((screen.getByRole("button", { name: /signing in/i }) as HTMLButtonElement).disabled).toBe(true);
    resolve(me());
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(login).toHaveBeenCalledTimes(1);
  });
});
