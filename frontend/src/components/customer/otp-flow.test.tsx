import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { CustomerSessionContext, type CustomerSession } from "@/lib/auth/customer-session";
import { OtpFlow } from "@/components/customer/otp-flow";

const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

function show(overrides: Partial<CustomerSession> = {}, onVerified = vi.fn().mockResolvedValue(undefined)) {
  const session: CustomerSession = {
    status: "anon", me: null,
    requestOtp: vi.fn().mockResolvedValue(undefined),
    verifyOtp: vi.fn(), googleLogin: vi.fn(), linkPhone: vi.fn(), updateProfile: vi.fn(),
    logout: vi.fn(), reload: vi.fn(),
    ...overrides,
  };
  render(
    <CustomerSessionContext.Provider value={session}>
      <OtpFlow submitLabel="Verify" onVerified={onVerified} />
    </CustomerSessionContext.Provider>,
  );
  return { session, onVerified };
}

beforeEach(() => toastError.mockReset());

describe("OtpFlow", () => {
  it("asks for the number, sends a code, then asks for the code", async () => {
    const { session } = show();
    expect(screen.queryByLabelText("Code")).toBeNull();
    await userEvent.type(screen.getByLabelText("Mobile number"), "93618 99061");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));

    expect(session.requestOtp).toHaveBeenCalledWith("93618 99061");
    expect(await screen.findByLabelText("Code")).toBeTruthy();
    expect(screen.getByText(/93618 99061/)).toBeTruthy(); // tells them where it went
  });

  it("verifies the code with the number they typed", async () => {
    const { onVerified } = show();
    await userEvent.type(screen.getByLabelText("Mobile number"), "9361899061");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await userEvent.type(await screen.findByLabelText("Code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(onVerified).toHaveBeenCalledWith("9361899061", "123456"));
  });

  it("shows the server's reason when sending fails and stays on the number step", async () => {
    show({ requestOtp: vi.fn().mockRejectedValue(new ApiError(429, "rate_limited", "Too Many Requests", null)) });
    await userEvent.type(screen.getByLabelText("Mobile number"), "9361899061");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Too Many Requests"));
    expect(screen.queryByLabelText("Code")).toBeNull();
  });

  it("tells them a wrong code is wrong and lets them try again", async () => {
    const onVerified = vi.fn().mockRejectedValueOnce(new ApiError(401, "invalid_otp", "Unauthorized", "That code is wrong or has expired.")).mockResolvedValueOnce(undefined);
    show({}, onVerified);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9361899061");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await userEvent.type(await screen.findByLabelText("Code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("That code is wrong or has expired."));

    const code = screen.getByLabelText("Code") as HTMLInputElement;
    await userEvent.clear(code);
    await userEvent.type(code, "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(2));
  });

  it("lets them go back and use a different number", async () => {
    show();
    await userEvent.type(screen.getByLabelText("Mobile number"), "9361899061");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await userEvent.click(await screen.findByRole("button", { name: "Use a different number" }));
    expect(screen.getByLabelText("Mobile number")).toBeTruthy();
    expect(screen.queryByLabelText("Code")).toBeNull();
  });

  it("only accepts digits in the code box", async () => {
    show();
    await userEvent.type(screen.getByLabelText("Mobile number"), "9361899061");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    const code = (await screen.findByLabelText("Code")) as HTMLInputElement;
    await userEvent.type(code, "12ab34");
    expect(code.value).toBe("1234");
  });
});
