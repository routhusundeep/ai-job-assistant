import { defineConfig } from "vite";
import { promises as fs } from "fs";
import { resolve } from "path";

export default defineConfig({
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        background: "src/background.ts",
        content: "src/content.ts",
        options: "src/options.ts",
      },
      output: {
        entryFileNames: "[name].js",
      },
    },
  },
  plugins: [
    {
      name: "copy-static",
      closeBundle: async () => {
        const files = ["src/manifest.json", "src/options.html"];
        await Promise.all(
          files.map(async (file) => {
            const data = await fs.readFile(resolve(__dirname, file));
            const dest = resolve(__dirname, "dist", file.split("/").pop() || "");
            await fs.writeFile(dest, data);
          })
        );
      },
    },
  ],
});
