/** @type {import('tailwindcss').Config} */
export default { content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'], theme: { extend: { colors: { canvas: '#F8FAF9', ink: '#0E2F37', signal: '#00838F', critical: '#C62828', moderate: '#E65100', stable: '#2E7D32' }, maxWidth: { dashboard: '1920px' } } }, plugins: [] }
