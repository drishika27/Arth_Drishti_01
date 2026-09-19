/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // A calmer, protective palette in the same family as Arth Bodh's
        // green — deep teal instead of forensic dark-mode/neon.
        guardian: "#0F5E5A",     // deep steady teal — primary
        harbor: "#EFF4F2",      // soft background, near-white with a cool tint
        deepink: "#111B1D",     // near-black text
        amber: "#C08A3E",       // warm accent for caution, not alarm
        signal: "#A83E32",      // used sparingly, only for real risk
        mist: "#5E7370",        // secondary text
      },
      fontFamily: {
        serif: ["'Source Serif 4'", "serif"],
        sans: ["Inter", "sans-serif"],
      },
    },
  },
  plugins: [],
}
