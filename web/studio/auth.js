// auth.js — การเข้าสู่ระบบ (Supabase Auth) ของหน้าเว็บ Thai GovDoc AI Studio
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
    if (cfg.misconfigured) {
      // เซิร์ฟเวอร์บนคลาวด์ยังไม่ได้ตั้ง Supabase: API จะปฏิเสธทุกคำขอ แจ้งผู้ดูแลแทนการแสดงหน้าที่ใช้ไม่ได้
      document.body.innerHTML = '<div style="max-width:32rem;margin:15vh auto;padding:1.5rem;font-family:sans-serif;line-height:1.6">' +
        '<h1 style="font-size:1.1rem;font-weight:600;margin-bottom:.5rem">ระบบยังไม่พร้อมใช้งาน</h1>' +
        '<p>ผู้ดูแลยังไม่ได้ตั้งค่าการเข้าสู่ระบบ (SUPABASE_URL และ SUPABASE_PUBLISHABLE_KEY) บนเซิร์ฟเวอร์</p></div>';
      return new Promise(() => {});
    }
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

  // ลงทะเบียนด้วยอีเมลที่ได้รับเชิญ (migration 15: trigger ผูกเข้าหน่วยงานตามคำเชิญ)
  // คืน true = เข้าสู่ระบบแล้ว, false = ต้องยืนยันอีเมลก่อน (โปรเจกต์เปิดการยืนยันอีเมล)
  async function signUp(email, password) {
    await loadConfig();
    const { data, error } = await client.auth.signUp({
      email, password, options: { emailRedirectTo: new URL(LOGIN_PAGE, location.href).href },
    });
    if (error) {
      const m = error.message || '';
      if (/already registered|already exists/i.test(m)) throw new Error('อีเมลนี้ลงทะเบียนไว้แล้ว — ใช้ "เข้าสู่ระบบ" แทน');
      if (/signups? not allowed|disabled/i.test(m)) throw new Error('ระบบยังไม่เปิดให้ลงทะเบียน — แจ้งผู้ดูแลให้เปิด Email sign up ใน Supabase');
      if (/password/i.test(m)) throw new Error('รหัสผ่านไม่ผ่านเงื่อนไขของระบบ: ' + m);
      throw new Error(m);
    }
    return !!data.session;
  }

  async function signOut() {
    if (client) await client.auth.signOut();
    goLogin();
  }

  window.GovDocAuth = {
    ready, token, signIn, signUp, signOut,
    serverMode: async () => (await loadConfig()).auth_required,
    config: loadConfig,
  };
})();
