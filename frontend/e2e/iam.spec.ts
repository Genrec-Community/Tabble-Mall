import { expect, test, type Browser, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import * as OTPAuth from "otpauth";

const state = JSON.parse(readFileSync(path.join(__dirname, ".state.json"), "utf8")) as {
  run: string;
  admin: { username: string; password: string };
  totpSecret: string;
  phone: string;
  otp: string;
};
const { run } = state;
const NEW_PASSWORD = "My-new-passw0rd!";

const totp = () =>
  new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(state.totpSecret) }).generate();

/** A brand-new browser context, i.e. a different person on a different device. */
async function newPerson(browser: Browser): Promise<Page> {
  return (await browser.newContext()).newPage();
}

/** Reads the one-time password out of the dialog, then closes it. */
async function takeTempPassword(page: Page): Promise<string> {
  const dialog = page.getByRole("dialog", { name: "Temporary password" });
  await expect(dialog).toBeVisible();
  const password = (await dialog.locator("dd").nth(1).innerText()).trim();
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(dialog).toBeHidden();
  return password;
}

/** Signs in with a temporary password and chooses a real one. */
async function firstLogin(page: Page, username: string, tempPassword: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(tempPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/login\/password$/);
  await page.getByLabel("Current password").fill(tempPassword);
  await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await page.getByLabel("Repeat new password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Save password" }).click();
}

test("platform admin → org owner → store owner → customer", async ({ browser }) => {
  const orgSlug = `phoenix-${run}`;
  const mallSlug = `phoenix-pune-${run}`;
  const storeSlug = `burger-hub-${run}`;
  const ownerUsername = `phoenix.owner.${run}`;
  const storeOwnerUsername = `burger.owner.${run}`;
  const cashierUsername = `burger.cashier.${run}`;

  // 1 ── The platform admin signs in (with an authenticator code) and creates an organization.
  const admin = await newPerson(browser);
  await admin.goto("/login");
  await admin.getByLabel("Username").fill(state.admin.username);
  await admin.getByLabel("Password").fill(state.admin.password);
  await admin.getByRole("button", { name: "Sign in" }).click();
  await admin.getByLabel("Authenticator code").fill(totp());
  await admin.getByRole("button", { name: "Sign in" }).click();
  await expect(admin).toHaveURL(/\/admin$/);

  await admin.getByRole("button", { name: "New organization" }).click();
  await admin.getByRole("dialog").getByLabel("Name", { exact: true }).fill("Phoenix Group");
  await admin.getByRole("dialog").getByLabel("Slug").fill(orgSlug);
  await admin.getByRole("dialog").getByLabel("Owner username").fill(ownerUsername);
  await admin.getByRole("dialog").getByLabel("Owner name").fill("Phoenix Owner");
  await admin.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  const ownerTempPassword = await takeTempPassword(admin);
  await expect(admin.getByRole("link", { name: "Phoenix Group" })).toBeVisible();

  // 2 ── The owner is made to choose a password, then sets up a mall and a store.
  const owner = await newPerson(browser);
  await firstLogin(owner, ownerUsername, ownerTempPassword);
  await expect(owner).toHaveURL(/\/org\/[0-9a-f-]{36}$/);
  const orgId = owner.url().split("/org/")[1];

  await owner.getByRole("link", { name: "Malls" }).click();
  await owner.getByRole("button", { name: "New mall" }).click();
  await owner.getByRole("dialog").getByLabel("Name", { exact: true }).fill("Phoenix Pune");
  await owner.getByRole("dialog").getByLabel("QR address").fill(mallSlug);
  await owner.getByRole("dialog").getByLabel("City").fill("Pune");
  await owner.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await owner.getByRole("link", { name: "Phoenix Pune" }).click();

  // A customer opens the mall's page before it has any store; the empty page is now cached.
  const early = await newPerson(browser);
  await early.goto(`/m/${mallSlug}`);
  await expect(early.getByText("No stores are open here yet")).toBeVisible();

  await owner.getByRole("button", { name: "New store" }).click();
  await owner.getByRole("dialog").getByLabel("Name", { exact: true }).fill("Burger Hub");
  await owner.getByRole("dialog").getByLabel("Slug").fill(storeSlug);
  await owner.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await owner.getByRole("link", { name: "Burger Hub" }).click();

  // 3 ── The owner creates the store's owner from the store's own staff page.
  await expect(owner).toHaveURL(/\/store\/[0-9a-f-]{36}$/);
  const storeUrl = owner.url();
  await owner.getByRole("link", { name: "Staff" }).click();
  await owner.getByRole("button", { name: "Add staff" }).click();
  await owner.getByRole("dialog").getByLabel("Username").fill(storeOwnerUsername);
  await owner.getByRole("dialog").getByLabel("Display name").fill("Burger Owner");
  await owner.getByRole("dialog").getByLabel("Role").selectOption({ label: "Store Owner" });
  await owner.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  const storeOwnerTempPassword = await takeTempPassword(owner);

  // 4 ── The store owner signs in, lands on their store, and adds a cashier.
  const storeOwner = await newPerson(browser);
  await firstLogin(storeOwner, storeOwnerUsername, storeOwnerTempPassword);
  await expect(storeOwner).toHaveURL(/\/store\/[0-9a-f-]{36}$/);
  await expect(storeOwner.getByRole("heading", { name: "Burger Hub" })).toBeVisible();
  await storeOwner.getByRole("link", { name: "Staff" }).click();
  await storeOwner.getByRole("button", { name: "Add staff" }).click();
  await storeOwner.getByRole("dialog").getByLabel("Username").fill(cashierUsername);
  await storeOwner.getByRole("dialog").getByLabel("Display name").fill("Burger Cashier");
  await storeOwner.getByRole("dialog").getByLabel("Role").selectOption({ label: "Store Staff" });
  await storeOwner.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await takeTempPassword(storeOwner);
  await expect(storeOwner.getByText(cashierUsername)).toBeVisible();

  // 5 ── A store owner has no business in the organization's staff pages.
  await storeOwner.goto(`/org/${orgId}/staff`);
  await expect(storeOwner.getByText("You don't have access to this area")).toBeVisible();
  expect(storeUrl).toContain("/store/");

  // 6 ── A customer scans the QR code, sees the store, and signs in with their phone.
  // The earlier visitor's cached "no stores" page must already be gone: the store shows up now.
  await early.reload();
  await expect(early.getByText("Burger Hub")).toBeVisible();
  const customer = await newPerson(browser);
  await customer.goto(`/m/${mallSlug}`);
  await expect(customer.getByRole("heading", { name: "Phoenix Pune" })).toBeVisible();
  await expect(customer.getByText("Burger Hub")).toBeVisible();

  await customer.goto("/account/login");
  await customer.getByLabel("Mobile number").fill(state.phone);
  await customer.getByRole("button", { name: "Send code" }).click();
  await customer.getByLabel("Code").fill(state.otp);
  await customer.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(customer).toHaveURL(/\/account$/);
  await expect(customer.getByText(`******${state.phone.slice(-4)}`)).toBeVisible();

  // 7 ── Reloading keeps everyone signed in (the refresh cookie restores each session).
  await customer.reload();
  await expect(customer.getByText(`******${state.phone.slice(-4)}`)).toBeVisible();
  await owner.reload(); // still on the store's Staff tab
  await expect(owner.getByText(storeOwnerUsername)).toBeVisible();
});
