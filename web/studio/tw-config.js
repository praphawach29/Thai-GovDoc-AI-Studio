// Tailwind config ร่วมของทุกหน้า (โหลดหลัง cdn.tailwindcss.com)
// โทนสีตามระบบออกแบบ "Sovereign Modernity": teal เข้มสื่อความเป็นทางการ + emerald สื่องาน AI
tailwind.config = {
  theme: {
    extend: {
      fontFamily: {
        sans: ['Prompt', 'sans-serif'],
        body: ['Sarabun', 'sans-serif'],
        doc: ['"TH SarabunIT๙"', '"TH Sarabun New"', 'Sarabun', 'serif'],
      },
      colors: {
        brand: {
          50: '#ecfdf5', 100: '#d1fae5', 200: '#a7f3d0', 500: '#10b981',
          600: '#00876c', 700: '#05614f', 800: '#064e40', 900: '#0a3641',
        },
      },
      boxShadow: {
        xs: '0 1px 2px 0 rgb(15 23 42 / 0.05)',
        paper: '0 4px 20px -2px rgb(0 0 0 / 0.08), 0 2px 6px -1px rgb(0 0 0 / 0.04)',
      },
    },
  },
};
