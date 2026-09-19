/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // The hub's palette sits as parent to both: deep ink-green root,
        // warm paper, with the gold thread that carries the "artha" motif.
        root: "#123832",       // deep, near-black green — the "one root"
        paper: "#F6F4EF",
        ink: "#141917",
        thread: "#B8862E",     // the shared gold thread across both products
        bodhwarm: "#0E6B4E",
        rakshacalm: "#0F5E5A",
      },
      fontFamily: {
        serif: ["'Source Serif 4'", "serif"],
        sans: ["Inter", "sans-serif"],
      },
    },
  },
  plugins: [],
}
