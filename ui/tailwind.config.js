/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Outfit', 'system-ui', 'sans-serif'],
        mono: ['"Space Mono"', 'monospace'],
      },
      colors: {
        base:    '#050A14',
        surface: '#0C1526',
        raised:  '#111F38',
        border:  '#1A2744',
        'border-bright': '#243759',
        accent:  '#3B82F6',
        'accent-dim': 'rgba(59,130,246,0.15)',
        'accent-glow': 'rgba(59,130,246,0.4)',
      },
      animation: {
        'pulse-slow': 'pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-right': 'slideRight 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
      },
      keyframes: {
        fadeIn: {
          '0%':   { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideRight: {
          '0%':   { transform: 'translateX(100%)' },
          '100%': { transform: 'translateX(0)' },
        },
      },
      boxShadow: {
        'accent': '0 0 0 1px rgba(59,130,246,0.4)',
        'glow':   '0 0 20px rgba(59,130,246,0.15)',
      },
    },
  },
  plugins: [],
}
