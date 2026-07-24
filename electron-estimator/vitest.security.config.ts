import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    allowOnly: false,
    include: ["tests/security/**/*.test.ts"],
    environment: "node"
  }
});
