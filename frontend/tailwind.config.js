/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--c-bg)',
        card: 'var(--c-card)',
        sheet: 'var(--c-sheet)',
        inset: 'var(--c-inset)',
        insetbg: 'var(--c-inset-on-bg)',
        separator: 'var(--c-separator)',
        text: 'var(--c-text)',
        hint: 'var(--c-hint)',
        onbtn: 'var(--c-onbtn)',
        blue: 'var(--c-blue)',
        blueweak: 'var(--c-blue-weak)',
        yellow: 'var(--c-yellow)',
        yellowpress: 'var(--c-yellow-press)',
        income: 'var(--c-income)',
        danger: 'var(--c-danger)',
        frozen: 'var(--c-frozen)',
        frozenbg: 'var(--c-frozen-bg)',
      },
      borderRadius: {
        card: '20px',
        inset: '14px',
        btn: '16px',
        sheet: '20px',
      },
      fontFamily: {
        sans: [
          'Onest',
          '-apple-system',
          'BlinkMacSystemFont',
          '"SF Pro Text"',
          '"Segoe UI"',
          'Roboto',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
};
