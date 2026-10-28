import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StoreOut } from "@/lib/api";
import { StoreProfileForm } from "@/components/store/store-profile-form";

const api = vi.hoisted(() => ({ storesUpdateStore: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const store: StoreOut = {
  id: "s1", organization_id: "o", mall_id: "m", name: "Burger Hub", slug: "burger-hub",
  status: "active", description: "Old blurb", commission_bps: null,
};

function show(props: { canEditProfile: boolean; canRename: boolean }) {
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <StoreProfileForm store={store} onSaved={onSaved} {...props} />
    </QueryClientProvider>,
  );
  return onSaved;
}

beforeEach(() => api.storesUpdateStore.mockReset());

describe("StoreProfileForm", () => {
  it("lets a store owner edit the description but not the name", () => {
    show({ canEditProfile: true, canRename: false });
    expect((screen.getByLabelText("Name") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("Description") as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("is read-only for people who cannot edit the profile", () => {
    show({ canEditProfile: false, canRename: false });
    expect((screen.getByLabelText("Description") as HTMLTextAreaElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("sends only the changed field", async () => {
    api.storesUpdateStore.mockResolvedValue({ data: { ...store, description: "New blurb" }, response: new Response() });
    const onSaved = show({ canEditProfile: true, canRename: false });
    const box = screen.getByLabelText("Description");
    await userEvent.clear(box);
    await userEvent.type(box, "New blurb");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.storesUpdateStore).toHaveBeenCalledWith({ path: { store_id: "s1" }, body: { description: "New blurb" } }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("includes the name only when the viewer may rename and did", async () => {
    api.storesUpdateStore.mockResolvedValue({ data: store, response: new Response() });
    show({ canEditProfile: true, canRename: true });
    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Burger Hub 2");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.storesUpdateStore.mock.calls[0][0].body).toEqual({ name: "Burger Hub 2" }));
  });

  it("clears the description when it is emptied", async () => {
    api.storesUpdateStore.mockResolvedValue({ data: { ...store, description: null }, response: new Response() });
    show({ canEditProfile: true, canRename: false });
    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.storesUpdateStore.mock.calls[0][0].body).toEqual({ description: null }));
  });

  it("does nothing when nothing changed", async () => {
    show({ canEditProfile: true, canRename: true });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.storesUpdateStore).not.toHaveBeenCalled();
  });
});
