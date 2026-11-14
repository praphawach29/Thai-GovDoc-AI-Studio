#!/usr/bin/env bash
# ทดสอบ migration บน PostgreSQL ชั่วคราวในเครื่อง (ไม่แตะ Supabase จริง)
#   bash supabase/tests/run_local.sh
# ต้องมี PostgreSQL 15+ (initdb, pg_ctl, psql)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MIGRATIONS="$HERE/../migrations"
PGBIN="${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}"
WORK="$(mktemp -d)"
PORT="${PGPORT_TEST:-54329}"

cleanup() { "$PGBIN/pg_ctl" -D "$WORK/data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

# initdb/postgres ไม่ยอมรันเป็น root
RUNAS=()
if [ "$(id -u)" = "0" ]; then
  id pgtest >/dev/null 2>&1 || useradd -M pgtest
  chown -R pgtest "$WORK"; chmod 755 "$WORK"
  RUNAS=(runuser -u pgtest --)
fi

"${RUNAS[@]}" "$PGBIN/initdb" -D "$WORK/data" -U postgres -A trust --locale=C.UTF-8 -E UTF8 >/dev/null
"${RUNAS[@]}" "$PGBIN/pg_ctl" -D "$WORK/data" -o "-p $PORT -k $WORK -c listen_addresses=''" -l "$WORK/log" -w start >/dev/null

PSQL=(psql -h "$WORK" -p "$PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -q -t -A)
"${PSQL[@]}" -f "$HERE/stub_supabase.sql"
for f in "$MIGRATIONS"/*.sql; do
  echo "apply $(basename "$f")"
  "${PSQL[@]}" -f "$f"
done
"${PSQL[@]}" -f "$HERE/db_test.sql"

# ออกเลขพร้อมกัน 20 การเชื่อมต่อ × 10 ครั้ง → ต้องได้ 200 เลขไม่ซ้ำ
for i in $(seq 1 20); do
  "${PSQL[@]}" -c "
    set role authenticated;
    set request.jwt.claims = '{\"sub\":\"00000000-0000-0000-0000-00000000000b\"}';
    select public.reserve_outgoing_number('PAR/', 'concurrent') from generate_series(1, 10);" >/dev/null &
done
wait
"${PSQL[@]}" -t -A -c "
  select case when count(*) = 200 and count(distinct doc_number) = 200 and max(reg_no) = 200
              then 'concurrency: 200 เลข ไม่ซ้ำ ต่อเนื่อง 1..200'
              else 'FAIL concurrency: ' || count(*) || ' rows, ' || count(distinct doc_number) || ' distinct' end
  from public.outgoing_register where book = 'outgoing:PAR/'" | tee "$WORK/conc"
grep -q '^concurrency:' "$WORK/conc"
"${PSQL[@]}" -t -A -c "set role authenticated;
  set request.jwt.claims = '{\"sub\":\"00000000-0000-0000-0000-00000000000b\"}';
  select 'audit chain after concurrency: ' || ok from public.verify_audit_chain()" | tee "$WORK/chain"
grep -q 'true' "$WORK/chain"
echo "ALL OK"
