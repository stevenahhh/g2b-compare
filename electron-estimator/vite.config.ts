import { defineConfig } from "vite";

export default defineConfig({
  root: "src/renderer",
  build: {
    emptyOutDir: false,
    outDir: "../../dist/renderer",
    rollupOptions: {
      output: {
        entryFileNames: "assets/index.js"
      }
    }
  }
});
