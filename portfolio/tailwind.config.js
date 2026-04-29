/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      boxShadow: {
        glow: "0 0 0 1px rgba(148, 163, 184, 0.2), 0 15px 40px rgba(15, 23, 42, 0.45)",
      },
      backgroundImage: {
        grid: "radial-gradient(circle at 1px 1px, rgba(148,163,184,.14) 1px, transparent 0)",
      },
    },
  },
  plugins: [],
};
