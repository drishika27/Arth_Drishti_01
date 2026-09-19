/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ledger: "#0E6B4E",
        paper: "#F4F6F4",
        ink: "#10181B",
        gold: "#B8862E",
        rust: "#B23B2E",
        slate: "#5B6B66",
      },
      fontFamily: {
        serif: ["'Source Serif 4'", "serif"],
        sans: ["Inter", "sans-serif"],
        devanagari: ["'Noto Sans Devanagari'", "sans-serif"],
      },
    },
  },
  plugins: [],
}
