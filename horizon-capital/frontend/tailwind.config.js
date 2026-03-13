/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "horizon-dark": "#0a0e17",
        "horizon-darker": "#060910",
        "horizon-card": "#111827",
        "horizon-border": "#1f2937",
        "accent-green": "#10b981",
        "accent-red": "#ef4444",
        "accent-blue": "#3b82f6",
        "accent-yellow": "#f59e0b",
        "accent-purple": "#8b5cf6",
      },
    },
  },
  plugins: [],
};
