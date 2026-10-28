import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "openapi.json",
  output: "src/lib/api",
  plugins: ["@hey-api/client-fetch", "@hey-api/typescript", "@hey-api/sdk"],
});
