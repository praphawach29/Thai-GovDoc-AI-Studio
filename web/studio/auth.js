// auth.js — การเข้าสู่ระบบ (Supabase Auth) ของหน้าเว็บ GovDoc Studio
// โหลดก่อน studio.js ทุกหน้า
//   - ถาม /api/v1/config ว่าเซิร์ฟเวอร์บังคับล็อกอินไหม
//   - โหมด Supabase: ยังไม่ล็อกอิน → ส่งไปหน้า login.html แล้วกลับมาหน้าเดิม
//   - โหมดเครื่องเดียว: ไม่ต้องล็อกอิน (ทุกอย่างทำงานเหมือนเดิม)
(function () {
  const LOGIN_PAGE = 'login.html';
  let client = null;
  let config = null;

  async function loadConfig() {
    if (config) return config;
    const res = await fetch('/api/v1/config');
    if (!res.ok) throw new Error('โหลดค่าตั้งของระบบไม่สำเร็จ');
    config = await res.json();
    if (config.auth_required) {
      if (!window.supabase?.createClient) throw new Error('โหลดไลบรารี Supabase ไม่สำเร็จ');
      client = window.supabase.createClient(config.supabase_url, config.supabase_publishable_key, {
        auth: { persistSession: true, autoRefreshToken: true },
      });
    }
    return config;
  }

  const isLoginPage = () => location.pathname.endsWith('/' + LOGIN_PAGE);
  let leaving = false;   // signOut() และเหตุการณ์ SIGNED_OUT เรียกพร้อมกันได้ — เปลี่ยนหน้าครั้งเดียว
  const goLogin = () => {
    if (leaving) return;
    leaving = true;
    const next = encodeURIComponent(location.pathname + location.search);
    location.replace(`${LOGIN_PAGE}?next=${next}`);
  };

  // token ล่าสุด (supabase-js ต่ออายุให้เอง) — คืน null ในโหมดเครื่องเดียว
  async function token() {
    await loadConfig();
    if (!client) return null;
    const { data } = await client.auth.getSession();
    return data.session?.access_token || null;
  }

  // ให้หน้าเว็บรอจนรู้ว่าล็อกอินแล้ว ก่อนเริ่มเรียก API
  const ready = (async () => {
    const cfg = await loadConfig();
    if (!cfg.auth_required || isLoginPage()) return cfg;
    if (!(await token())) { goLogin(); return new Promise(() => {}); }   // หยุดหน้าไว้ระหว่างเปลี่ยนหน้า
    client.auth.onAuthStateChange((event) => { if (event === 'SIGNED_OUT') goLogin(); });
    return cfg;
  })();

  async function signIn(email, password) {
    await loadConfig();
    const { error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw new Error(error.message === 'Invalid login credentials' ? 'อีเมลหรือรหัสผ่านไม่ถูกต้อง' : error.message);
  }

  async function signOut() {
    if (client) await client.auth.signOut();
    goLogin();
  }

  window.GovDocAuth = {
    ready, token, signIn, signOut,
    serverMode: async () => (await loadConfig()).auth_required,
    config: loadConfig,
  };
})();
