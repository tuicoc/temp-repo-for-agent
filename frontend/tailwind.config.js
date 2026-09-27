/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Paper is white and text is black, not a tinted near-black. Two
        // greys for secondary text, one cool grey for rules, one wash for a
        // selected or hovered row. One accent — a steel blue with the calm
        // of a telephony console — carries every "this is live, this is
        // chosen, this is a link" meaning. Red is for destruction only.
        ink: '#000000',
        muted: '#5F6368',
        faint: '#9AA0A6',
        line: '#E1E3E6',
        'line-2': '#CDD1D6',
        surface: '#FFFFFF',
        hover: '#F2F3F5',
        bubble: '#F2F3F5',
        accent: '#2F5D8A',
        'accent-tint': '#E8EEF5',
        danger: '#B3261E',
      },
      fontFamily: {
        // Designed for Vietnamese diacritics, which every reply on this
        // screen has. One family; weight and size carry the hierarchy.
        sans: ['"Be Vietnam Pro"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['Menlo', '"Cascadia Code"', 'Consolas', 'monospace'],
      },
      boxShadow: {
        input: '0 0 0 3px rgba(47,93,138,0.16)',
      },
    },
  },
  plugins: [],
}
