/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "horizon-dark": "#0c1017",
        "horizon-darker": "#080b11",
        "horizon-card": "#111723",
        "horizon-border": "#1c2433",
        "accent-green": "#10b981",
        "accent-red": "#ef4444",
        "accent-blue": "#6b8afd",
        "accent-yellow": "#f59e0b",
        "accent-purple": "#a78bfa",
      },
    },
  },
  plugins: [],
};
