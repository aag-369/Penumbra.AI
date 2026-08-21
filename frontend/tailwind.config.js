/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#08090c",
          900: "#0b0d12",
          850: "#0e1015",
          800: "#12151c",
          700: "#1a1e28",
          600: "#242a36",
          500: "#333a4a",
        },
        mist: { DEFAULT: "#e6e8ec", dim: "#9aa3b2", faint: "#69728a" },
        // Violet reads as "penumbra" without being purple-for-its-own-sake.
        umbra: { DEFAULT: "#8b5cf6", bright: "#a78bfa", deep: "#6d28d9" },
        // Cyan marks anything encrypted. Used consistently and nowhere else,
        // so a reader learns the code in one screen.
        cipher: { DEFAULT: "#22d3ee", dim: "#0e7490" },
        ok: "#34d399",
        warn: "#fbbf24",
        bad: "#f87171",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(139,92,246,0.35), 0 0 32px -8px rgba(139,92,246,0.45)",
        cipher: "0 0 0 1px rgba(34,211,238,0.30), 0 0 28px -10px rgba(34,211,238,0.5)",
      },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "0% 50%" }, "100%": { backgroundPosition: "200% 50%" } },
        pulseSoft: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.45" } },
        riseIn: { "0%": { opacity: "0", transform: "translateY(6px)" }, "100%": { opacity: "1", transform: "none" } },
      },
      animation: {
        shimmer: "shimmer 2.2s linear infinite",
        pulseSoft: "pulseSoft 1.6s ease-in-out infinite",
        riseIn: "riseIn 260ms ease-out both",
      },
    },
  },
  plugins: [],
};
