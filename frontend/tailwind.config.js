/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Warm, low-contrast palette. Long telesales conversations are read
        // for minutes at a time, and a stark white page is tiring.
        app: {
          bg: '#F7F3EA',
          sidebar: '#EFE8DC',
          surface: '#FFFDF8',
          border: '#E2D6C5',
          accent: '#B86F50',
          'accent-dim': '#F4DED1',
          dark: '#211914',
          body: '#4A4038',
          muted: '#776B60',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        input: '0 0 0 3px rgba(184,111,80,0.12)',
      },
    },
  },
  plugins: [],
}
