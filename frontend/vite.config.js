import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";

// Developer-only login prefill values (frontend/.env). They must never be
// compiled into a build: everything in dist/ is public JavaScript.
const DEFAULT_CREDENTIAL_KEYS = ["VITE_DEFAULT_EMAIL", "VITE_DEFAULT_PASSWORD"];

// Fails the build if a prefill value appears in any emitted file, however
// the build was started (CI, deploy_frontend.sh, Docker, a laptop). The
// values are compared, never printed.
function noDefaultCredentialsInBundle(env) {
  const values = DEFAULT_CREDENTIAL_KEYS
    .map((key) => [key, (env[key] || "").trim()])
    .filter(([, value]) => value.length >= 6);
  return {
    name: "zoiko-no-default-credentials-in-bundle",
    apply: "build",
    generateBundle(_options, bundle) {
      for (const [fileName, output] of Object.entries(bundle)) {
        const text = output.type === "chunk"
          ? output.code
          : typeof output.source === "string" ? output.source : Buffer.from(output.source).toString("utf8");
        for (const [key, value] of values) {
          if (text.includes(value)) {
            this.error(`${key}'s value was compiled into ${fileName}. Login prefill values must never ship; `
              + "read them only behind import.meta.env.DEV (see LoginPage.jsx).");
          }
        }
      }
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL(".", import.meta.url)), "VITE_");
  return {
    plugins: [noDefaultCredentialsInBundle(env)],
    server: {
      port: 5173,
      host: true,
    },
    build: {
      chunkSizeWarningLimit: 1500,
      sourcemap: false,
    },
  };
});
