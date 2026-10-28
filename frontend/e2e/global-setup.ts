import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

/**
 * Runs once before the tests, after the stack is up: creates the first Platform Admin with the
 * real `seed-admin` command (exactly what an operator does) and writes the credentials the spec
 * needs. Names carry a per-run suffix so repeated runs never collide.
 */
export default function globalSetup() {
  const run = Date.now().toString(36);
  const admin = { username: `root-${run}`, password: "e2e-Admin-Pass-1" };
  const command = process.env.E2E_SEED_COMMAND ?? "uv run python -m mallt.cli seed-admin";
  const cwd = process.env.E2E_SEED_CWD ?? path.resolve(__dirname, "../../backend");

  const output = execSync(`${command} --username ${admin.username} --display-name "E2E Admin"`, {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      MALLT_ADMIN_PASSWORD: admin.password,
      DATABASE_URL: process.env.E2E_DATABASE_URL ?? "postgresql+asyncpg://postgres:test@localhost:5432/mallt_e2e",
    },
  });
  const uri = output.match(/otpauth:\/\/\S+/)?.[0];
  if (!uri) throw new Error(`seed-admin printed no authenticator URI:\n${output}`);
  const totpSecret = new URL(uri).searchParams.get("secret");

  // A fresh mobile number each run (the API allows only a few codes per number per window).
  const phone = `9${Math.floor(Math.random() * 1e9).toString().padStart(9, "0")}`;

  mkdirSync(path.join(__dirname), { recursive: true });
  writeFileSync(
    path.join(__dirname, ".state.json"),
    JSON.stringify({ run, admin, totpSecret, phone, otp: "123456" }, null, 2),
  );
}
