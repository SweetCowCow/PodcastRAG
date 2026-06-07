#!/usr/bin/env bash
# b23 prod chat smoke (topic-prefilter-transcript-aware, task 5.1).
# Logs in via e2e backdoor (admin) and fires the b23 question with
# debug_trace=true, then reports whether EP107 (8b3d4c1d) appears in the
# topic-prefilter candidates / citations.
set -euo pipefail

API="https://podcastrag-api.zeabur.app"
ORIGIN="https://app.podcastrag.app"
SHOW="45fc2462-17cf-42f5-98a7-68fe1a222228"
EP107="8b3d4c1d"
JAR="$(mktemp)"
TOKEN="$(cat ~/.config/podcastrag/e2e-token)"

# 1. e2e admin login → cookie jar (don't print token / cookies)
curl -sS -c "$JAR" -b "$JAR" -o /dev/null \
  "$API/auth/_e2e_login?token=$TOKEN"
# 2. /me — canonical csrf source is the response body (not the cookie)
ME="$(curl -sS -b "$JAR" -H "Origin: $ORIGIN" "$API/me")"
CSRF="$(echo "$ME" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("csrf_token",""))' 2>/dev/null)"
echo "== /me role: $(echo "$ME" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("role"))' 2>/dev/null || echo '?')"
if [ -z "$CSRF" ]; then echo "FAIL: no csrf_token in /me body (login failed)"; echo "$ME"; exit 1; fi

# 3. b23 chat query with debug_trace
Q='迪拉跟 Leo王 是怎麼從不認識變成合作夥伴的？節目裡有提過他們第一次見面的故事嗎？'
BODY="$(python3 -c "import json,sys;print(json.dumps({'mode':'chat','question':sys.argv[1],'messages':[]}))" "$Q")"
RESP="$(curl -sS -b "$JAR" -H "Origin: $ORIGIN" -H "X-CSRF-Token: $CSRF" \
  -H "Content-Type: application/json" \
  -X POST "$API/shows/$SHOW/query?debug_trace=true" -d "$BODY")"

echo "$RESP" > /tmp/b23_smoke_resp.json
# 4. analyse
python3 - "$EP107" <<'PY'
import json, sys
ep107 = sys.argv[1]
r = json.load(open('/tmp/b23_smoke_resp.json'))
ans = r.get('answer','')
print("\n== answer (first 400 chars) ==")
print(ans[:400])
cits = r.get('citations',[]) or []
print(f"\n== citations: {len(cits)} ==")
ep107_cited = False
for c in cits:
    t = c.get('episode_title','') or ''
    mark = ''
    if 'EP107' in t or ep107 in str(c.get('episode_id','')):
        ep107_cited = True; mark = '  <-- EP107'
    print(f"  - {t[:50]}{mark}")
tcs = r.get('tool_calls') or []
print(f"\n== tool_calls: {len(tcs)} ==")
ep107_candidate = False
for tc in tcs:
    name = tc.get('name')
    args = tc.get('args',{})
    print(f"  * {name}  args={json.dumps(args, ensure_ascii=False)[:160]}")
    rf = tc.get('result_full') or tc.get('result_summary') or ''
    if name == 'search_with_topic_prefilter':
        try:
            d = json.loads(rf)
            print(f"      prefilter_source={d.get('prefilter_source')} "
                  f"prefilter_episode_count={d.get('prefilter_episode_count')} "
                  f"fallback={d.get('fallback_to_full_pool')} rerank={d.get('rerank_applied')}")
            for ch in (d.get('chunks') or []):
                et = ch.get('episode_title','') or str(ch.get('episode_id',''))
                if 'EP107' in et or ep107 in str(ch.get('episode_id','')):
                    ep107_candidate = True
        except Exception as e:
            if 'EP107' in rf or ep107 in rf:
                ep107_candidate = True
            print(f"      (result_full not JSON: {e})")
    if 'EP107' in rf or ep107 in rf:
        ep107_candidate = True

print("\n== VERDICT ==")
print(f"EP107 in prefilter candidates/chunks: {ep107_candidate}")
print(f"EP107 cited in answer sources:        {ep107_cited}")
PY
