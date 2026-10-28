import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TempPasswordDialog } from "@/components/temp-password-dialog";

describe("TempPasswordDialog", () => {
  it("shows the username and temporary password with a warning that it appears once", () => {
    render(<TempPasswordDialog secret={{ username: "phoenix.owner", password: "Xy7-temp-pass-9" }} onClose={vi.fn()} />);
    expect(screen.getByText("phoenix.owner")).toBeTruthy();
    expect(screen.getByText("Xy7-temp-pass-9")).toBeTruthy();
    expect(screen.getByText(/only once/i)).toBeTruthy();
  });

  it("copies the password to the clipboard", async () => {
    const user = userEvent.setup();
    render(<TempPasswordDialog secret={{ username: "u", password: "Xy7-temp-pass-9" }} onClose={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Copy password" }));
    expect(await navigator.clipboard.readText()).toBe("Xy7-temp-pass-9");
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
  });

  it("renders nothing when there is no secret, and reports closing", async () => {
    const { rerender } = render(<TempPasswordDialog secret={null} onClose={vi.fn()} />);
    expect(screen.queryByText(/temporary password/i)).toBeNull();

    const onClose = vi.fn();
    rerender(<TempPasswordDialog secret={{ username: "u", password: "p-p-p-p-p-p-p-p" }} onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });
});
