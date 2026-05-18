/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './static/index.html',
    './static/app.js',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      colors: {
        yan: {
          bg: '#07070a',
          panel: '#11111a',
          panel2: '#171724',
          line: 'rgba(255,255,255,.10)',
          hot: '#e94560',
          pink: '#ffd6dd',
          orange: '#ffa500',
          blue: '#8c8cff',
          green: '#7bd88f',
        },
      },
      boxShadow: {
        glow: '0 0 34px rgba(233, 69, 96, .22)',
        panel: '0 24px 80px rgba(0, 0, 0, .38)',
      },
      backgroundImage: {
        'yan-radial': 'radial-gradient(circle at 18% 0%, rgba(233,69,96,.20), transparent 32%), radial-gradient(circle at 86% 12%, rgba(140,140,255,.12), transparent 30%), linear-gradient(135deg, #07070a 0%, #0c0c12 54%, #09090d 100%)',
      },
    },
  },
  plugins: [require('@tailwindcss/forms')],
};
