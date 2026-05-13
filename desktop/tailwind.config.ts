import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "SF Pro Display",
          "Segoe UI",
          "Noto Sans",
          "system-ui",
          "sans-serif",
        ],
      },
      colors: {
        shell: "rgb(var(--tw-shell) / <alpha-value>)",
        graphite: "rgb(var(--tw-graphite) / <alpha-value>)",
        ink: "rgb(var(--tw-ink) / <alpha-value>)",
        muted: "rgb(var(--tw-muted) / <alpha-value>)",
        line: "rgb(var(--tw-line) / <alpha-value>)",
        warm: "rgb(var(--tw-warm) / <alpha-value>)",
        panel: "rgb(var(--tw-panel) / <alpha-value>)",
        bluewash: "rgb(var(--tw-bluewash) / <alpha-value>)",
      },
      boxShadow: {
        device:
          "0 28px 80px rgba(0,0,0,0.42), inset 0 1px 0 rgba(255,255,255,0.86)",
        soft:
          "0 18px 40px rgba(65,55,38,0.12), 0 2px 8px rgba(65,55,38,0.08)",
        insetPanel:
          "inset 0 1px 0 rgba(255,255,255,0.72), inset 0 -10px 24px rgba(55,45,32,0.05)",
        control:
          "0 12px 24px rgba(0,0,0,0.26), inset 0 1px 0 rgba(255,255,255,0.08)",
      },
      borderRadius: {
        device: "28px",
        module: "10px",
      },
    },
  },
  plugins: [],
} satisfies Config;
