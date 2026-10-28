import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GoogleButton } from "@/components/customer/google-button";

afterEach(() => {
  document.head.querySelectorAll("script").forEach((s) => s.remove());
  delete (window as unknown as { google?: unknown }).google;
});

describe("GoogleButton", () => {
  it("renders nothing and loads nothing when Google sign-in is not configured", () => {
    const { container } = render(<GoogleButton clientId="" onCredential={vi.fn()} />);
    expect(container.innerHTML).toBe("");
    expect(document.head.querySelector('script[src*="accounts.google.com"]')).toBeNull();
  });

  it("loads Google's script once configured", () => {
    render(<GoogleButton clientId="abc.apps.googleusercontent.com" onCredential={vi.fn()} />);
    expect(document.head.querySelector('script[src="https://accounts.google.com/gsi/client"]')).toBeTruthy();
  });

  it("initialises Google with the client id and hands back the credential", () => {
    const initialize = vi.fn();
    const renderButton = vi.fn();
    (window as unknown as { google: unknown }).google = { accounts: { id: { initialize, renderButton } } };
    const onCredential = vi.fn();

    render(<GoogleButton clientId="abc.apps.googleusercontent.com" onCredential={onCredential} />);

    expect(initialize).toHaveBeenCalledTimes(1);
    const options = initialize.mock.calls[0][0] as { client_id: string; callback: (r: { credential: string }) => void };
    expect(options.client_id).toBe("abc.apps.googleusercontent.com");
    options.callback({ credential: "the-id-token" });
    expect(onCredential).toHaveBeenCalledWith("the-id-token");
    expect(renderButton).toHaveBeenCalled();
  });
});
