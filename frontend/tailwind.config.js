/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Taken from the reference project rather than invented. The page is
        // white, not the warm parchment its tailwind config also defines — the
        // components use these values, and matching the config instead of the
        // components produced a different-looking app.
        ink: '#1A1A1A',
        muted: '#6B6B6B',
        faint: '#9A9A9A',
        line: '#E5E5E5',
        'line-2': '#DEDEDE',
        surface: '#FFFFFF',
        sidebar: '#F3F3F3',
        hover: '#F7F7F7',
        bubble: '#EFEFEF',
        accent: '#B86F50',
        'accent-tint': '#F4DED1',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"Fira Code"', '"Cascadia Code"', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      boxShadow: {
        input: '0 0 0 3px rgba(184,111,80,0.12)',
      },
    },
  },
  plugins: [],
}
