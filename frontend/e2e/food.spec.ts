import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import * as OTPAuth from "otpauth";

/**
 * The whole food-ordering journey with REAL parts: the API, the website, nginx, a real print-agent
 * process, and two fake network printers (TCP servers that capture the bytes the agent sends).
 */
const state = JSON.parse(readFileSync(path.join(__dirname, ".state.json"), "utf8")) as {
  run: string;
  admin: { username: string; password: string };
  totpSecret: string;
  phone: string;
  otp: string;
};
const API = "http://localhost:8080/api/v1";
const PASSWORD = "My-new-passw0rd!";
const run = `${state.run}f`;
const AGENT_PYTHON = process.env.E2E_AGENT_PYTHON ?? path.resolve(__dirname, "../../print-agent/.venv/bin/python");
const AGENT_DIR = path.resolve(__dirname, "../../print-agent");

/** A printer on the network: accepts a connection and keeps every byte it is sent. */
function fakePrinter() {
  const jobs: Buffer[] = [];
  const server = net.createServer((socket) => {
    const chunks: Buffer[] = [];
    socket.on("data", (c) => chunks.push(c));
    socket.on("end", () => jobs.push(Buffer.concat(chunks)));
    socket.on("error", () => undefined);
  });
  return new Promise<{ port: number; jobs: Buffer[]; text: () => string; close: () => void }>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as net.AddressInfo).port;
      resolve({ port, jobs, text: () => jobs.map((j) => j.toString("latin1")).join("\n=====\n"), close: () => server.close() });
    });
  });
}

async function post(request: APIRequestContext, url: string, token: string | null, data: unknown) {
  const res = await request.post(`${API}${url}`, { data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  expect(res.ok(), `${url} -> ${res.status()} ${await res.text()}`).toBeTruthy();
  return res.status() === 204 ? null : res.json();
}

async function login(request: APIRequestContext, username: string, password: string, totpSecret?: string): Promise<string> {
  const data: Record<string, string> = { username, password };
  if (totpSecret) data.totp_code = new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(totpSecret) }).generate();
  return (await post(request, "/auth/staff/login", null, data)).access_token;
}

/** Create a staff member with a real password so the UI can sign in as them. */
async function onboard(request: APIRequestContext, creator: string, url: string, username: string, role_key: string) {
  const created = await post(request, url, creator, { username, display_name: username, role_key });
  const first = await login(request, username, created.temp_password);
  await post(request, "/auth/staff/password", first, { current_password: created.temp_password, new_password: PASSWORD });
}

async function signIn(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("customer orders from a store; the kitchen ticket and bill really print", async ({ browser, request }) => {
  test.setTimeout(240_000);
  const orgSlug = `food-${run}`;
  const mallSlug = `food-mall-${run}`;
  const storeSlug = `burger-${run}`;
  const ownerName = `food.owner.${run}`;
  const storeOwnerName = `food.store.${run}`;
  const kitchen = await fakePrinter();
  const counter = await fakePrinter();
  let agent: ChildProcess | undefined;

  try {
    // ── Set-up through the API (the UI for this part is covered by iam.spec.ts) ──────────────
    const admin = await login(request, state.admin.username, state.admin.password, state.totpSecret);
    const org = await post(request, "/orgs", admin, { name: "Food Group", slug: orgSlug, owner: { username: ownerName, display_name: "Food Owner" } });
    const ownerFirst = await login(request, ownerName, org.temp_password);
    await post(request, "/auth/staff/password", ownerFirst, { current_password: org.temp_password, new_password: PASSWORD });
    const owner = await login(request, ownerName, PASSWORD);
    const mall = await post(request, `/orgs/${org.org.id}/malls`, owner, { name: "Food Mall", slug: mallSlug, city: "Pune" });
    const store = await post(request, `/malls/${mall.id}/stores`, owner, { name: "Burger Hub", slug: storeSlug });
    await onboard(request, owner, `/stores/${store.id}/staff`, storeOwnerName, "store_owner");

    // ── The store owner builds a menu and sets up the shop in the browser ─────────────────────
    const ownerPage = await (await browser.newContext()).newPage();
    await signIn(ownerPage, storeOwnerName);
    await expect(ownerPage).toHaveURL(new RegExp(`/store/${store.id}$`));

    await ownerPage.getByRole("link", { name: "Settings" }).click();
    await ownerPage.getByLabel("Fast food").check();
    await ownerPage.getByLabel("GSTIN").fill("27AAPFU0939F1ZV");
    await ownerPage.getByRole("button", { name: "Save settings" }).click();
    await expect(ownerPage.getByText("Saved.").first()).toBeVisible();

    await ownerPage.getByRole("link", { name: "Menu" }).click();
    await ownerPage.getByLabel("New category").fill("Burgers");
    await ownerPage.getByRole("button", { name: "Add category" }).click();
    await expect(ownerPage.getByRole("heading", { name: "Burgers" })).toBeVisible();
    await ownerPage.getByRole("button", { name: "Add an item" }).click();
    const form = ownerPage.getByRole("dialog");
    await form.getByLabel("Name", { exact: true }).fill("Cheese Burger");
    await form.getByLabel("Category").selectOption({ label: "Burgers" });
    await form.getByLabel("Size 1 name").fill("Regular");
    await form.getByLabel("Size 1 price").fill("120");
    await form.getByRole("button", { name: "Add a size" }).click();
    await form.getByLabel("Size 2 name").fill("Large");
    await form.getByLabel("Size 2 price").fill("180");
    await form.getByRole("button", { name: "Add an add-on group" }).click();
    await form.getByLabel("Group 1 name").fill("Extras");
    await form.getByLabel("Group 1 option 1 name").fill("Extra cheese");
    await form.getByLabel("Group 1 option 1 extra price").fill("20");
    await form.getByRole("button", { name: "Add to menu" }).click();
    await expect(ownerPage.getByText("Cheese Burger").first()).toBeVisible();

    // ── Pair a PC, start the real agent, add the two (fake) printers ─────────────────────────
    await ownerPage.getByRole("link", { name: "Printers" }).click();
    await ownerPage.getByLabel("Name of the PC").fill("Counter PC");
    await ownerPage.getByRole("button", { name: "Pair a PC" }).click();
    const command = await ownerPage.getByTestId("cmd-linux").innerText();
    const token = command.match(/--token (\S+)/)![1];
    await ownerPage.getByRole("button", { name: "I have installed it" }).click();

    const dir = mkdtempSync(path.join(tmpdir(), "mallt-agent-"));
    const config = path.join(dir, "agent.toml");
    writeFileSync(config, `url = "http://localhost:8080"\ntoken = "${token}"\n`);
    agent = spawn(AGENT_PYTHON, ["-m", "print_agent", "--config", config], { cwd: AGENT_DIR, stdio: "ignore" });
    await expect(async () => {
      await ownerPage.reload();
      await expect(ownerPage.getByText("Online")).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 40_000 });

    async function addPrinter(name: string, role: "Kitchen tickets (no prices)" | "Customer bills", port: number) {
      await ownerPage.getByRole("button", { name: "Add a network printer by address" }).click();
      const dialog = ownerPage.getByRole("dialog");
      await dialog.getByLabel("Name", { exact: true }).fill(name);
      await dialog.getByLabel("What it prints").selectOption({ label: role });
      await dialog.getByLabel("Printer address (IP or IP:port)").fill(`127.0.0.1:${port}`);
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(ownerPage.getByRole("listitem").filter({ hasText: name }).first()).toBeVisible();
    }
    await addPrinter("Kitchen printer", "Kitchen tickets (no prices)", kitchen.port);
    await addPrinter("Counter printer", "Customer bills", counter.port);

    // A test page proves the whole chain: dashboard → API → agent → printer.
    const kitchenRow = ownerPage.locator("li", { hasText: "Kitchen printer" }).filter({ has: ownerPage.getByRole("button", { name: "Test print" }) });
    await kitchenRow.getByRole("button", { name: "Test print" }).click();
    await expect.poll(() => kitchen.text(), { timeout: 20_000 }).toContain("TEST PRINT");

    // ── A customer orders ───────────────────────────────────────────────────────────────────
    const customer = await (await browser.newContext()).newPage();
    await customer.goto(`/account/login?next=/m/${mallSlug}/s/${storeSlug}`);
    await customer.getByLabel("Mobile number").fill(state.phone);
    await customer.getByRole("button", { name: "Send code" }).click();
    await customer.getByLabel("Code").fill(state.otp);
    await customer.getByRole("button", { name: "Verify and sign in" }).click();
    await expect(customer.getByRole("heading", { name: "Burger Hub" })).toBeVisible();
    await expect(customer.getByText("Cheese Burger")).toBeVisible();

    await customer.getByRole("button", { name: "Add Cheese Burger" }).click();
    const picker = customer.getByRole("dialog");
    await picker.getByLabel(/Large/).check();
    await picker.getByLabel(/Extra cheese/).check();
    await picker.getByLabel("Note for the kitchen (optional)").fill("no onion");
    await picker.getByRole("button", { name: /Add to cart/ }).click();
    await expect(picker).toBeHidden({ timeout: 10_000 }).catch(async (e) => {
      throw new Error(`${e.message}\nPAGE: ${(await customer.locator("body").innerText()).replace(/\n/g, " / ").slice(0, 700)}`);
    });
    await customer.getByRole("link", { name: /Cart/ }).click();
    await expect(customer.getByText("Cheese Burger (Large)")).toBeVisible();
    await customer.getByRole("button", { name: /Place order/ }).click();

    await expect(customer).toHaveURL(/\/account\/orders\//);
    await expect(customer.getByText("Waiting for the store to accept").first()).toBeVisible();
    const code = (await customer.getByLabel(/Pickup code/).innerText()).trim();
    expect(code).toMatch(/^\d{4}$/);

    // ── The store sees it live, accepts, and the kitchen ticket prints ───────────────────────
    await ownerPage.getByRole("link", { name: "Orders" }).click();
    const card = ownerPage.getByRole("article", { name: "Order 1" });
    await expect(card).toBeVisible();
    await expect(card).toContainText("Cheese Burger");
    await card.getByRole("button", { name: "Accept" }).click();
    await expect.poll(() => kitchen.text(), { timeout: 20_000 }).toContain("Cheese Burger (Large)");
    const ticket = kitchen.jobs.at(-1)!.toString("latin1");
    expect(ticket).toContain("#1");
    expect(ticket).toContain("+ Extra cheese");
    expect(ticket).toContain("no onion");
    expect(ticket).not.toContain(code); // the code is the customer's proof of purchase
    expect(ticket).not.toMatch(/₹|Rs|TOTAL|\d+\.\d\d/); // a kitchen ticket carries no money
    await expect(customer.getByText("Accepted — the store is about to start").first()).toBeVisible({ timeout: 20_000 });

    // ── Preparing → ready: the customer's bill prints at the counter ────────────────────────
    await ownerPage.getByRole("article", { name: "Order 1" }).getByRole("button", { name: "Start preparing" }).click();
    await ownerPage.getByRole("article", { name: "Order 1" }).getByRole("button", { name: "Mark ready" }).click();
    await expect.poll(() => counter.text(), { timeout: 20_000 }).toContain("TOTAL");
    const bill = counter.jobs.at(-1)!.toString("latin1");
    expect(bill).toContain("200.00");
    expect(bill).toContain("GSTIN: 27AAPFU0939F1ZV");
    expect(bill).toContain("CGST @2.5%");
    expect(bill).not.toContain(code);
    await expect(customer.getByText("Ready — show your code at the counter").first()).toBeVisible({ timeout: 20_000 });

    // ── Pickup with the code ────────────────────────────────────────────────────────────────
    await ownerPage.getByRole("article", { name: "Order 1" }).getByRole("button", { name: /collecting/ }).click();
    const collect = ownerPage.getByRole("dialog");
    const wrong = code === "0000" ? "1111" : "0000";
    await collect.getByLabel("Pickup code").fill(wrong);
    await collect.getByRole("button", { name: "Confirm pickup" }).click();
    await expect(ownerPage.getByText("That pickup code is not right.")).toBeVisible();
    await collect.getByLabel("Pickup code").fill(code);
    await collect.getByRole("button", { name: "Confirm pickup" }).click();
    await expect(ownerPage.getByText("Order 1")).toHaveCount(0);
    await expect(customer.getByText("Collected").first()).toBeVisible({ timeout: 20_000 });
  } finally {
    agent?.kill();
    kitchen.close();
    counter.close();
  }
});
