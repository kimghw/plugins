#!/bin/bash
# MCP 서버 자동 설정 (Codex + Gemini)
#
# 사용법:
#   bash setup_mcp.sh                      # 전체 설정 (setup에서 호출)
#   bash setup_mcp.sh --check-only         # 전체 체크만 (exit code 반환)
#   bash setup_mcp.sh --check-only codex   # Codex만 체크
#   bash setup_mcp.sh --check-only gemini  # Gemini만 체크
#
# 종료 코드:
#   0 = 모두 정상
#   1 = 설정 필요 (--check-only 모드)
#   2 = 설정 실패 (설정 모드)

# --- 설정 ---
CLAUDE_JSON="$HOME/.claude.json"
CODEX_AUTH="$HOME/.codex/auth.json"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../../../../.." 2>/dev/null && pwd)}"
SETTINGS_LOCAL="$PROJECT_DIR/.claude/settings.local.json"

CHECK_ONLY=false
CHECK_TARGET="all"  # all / codex / gemini

# 인자 파싱
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check-only)
            CHECK_ONLY=true
            shift
            if [[ $# -gt 0 && "$1" != --* ]]; then
                CHECK_TARGET="$1"
                shift
            fi
            ;;
        *) shift ;;
    esac
done

# CHECK_TARGET 검증
case "$CHECK_TARGET" in
    all|codex|gemini) ;;
    *)
        echo "ERROR: 유효하지 않은 대상: '$CHECK_TARGET' (허용: all, codex, gemini)"
        exit 2
        ;;
esac

# --- 유틸리티 ---
STATUS_NEED=0

print_status() {
    local label="$1" status="$2" detail="${3:-}"
    case "$status" in
        OK)   echo "  [OK]          $label${detail:+ — $detail}" ;;
        SKIP) echo "  [SKIP]        $label${detail:+ — $detail}" ;;
        NEED) echo "  [NEED_ACTION] $label${detail:+ — $detail}"; STATUS_NEED=1 ;;
        FAIL) echo "  [FAIL]        $label${detail:+ — $detail}"; STATUS_NEED=1 ;;
    esac
}

# JSON에서 키 존재 확인
json_has_key() {
    local _file="$1" _key="$2"
    python3 - "$_file" "$_key" <<'PYEOF'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    servers = data.get('mcpServers', {})
    sys.exit(0 if sys.argv[2] in servers else 1)
except Exception:
    sys.exit(1)
PYEOF
}

# settings.local.json에서 권한 확인
has_permission() {
    local _file="$1" _perm="$2"
    python3 - "$_file" "$_perm" <<'PYEOF'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    allows = data.get('permissions', {}).get('allow', [])
    sys.exit(0 if sys.argv[2] in allows else 1)
except Exception:
    sys.exit(1)
PYEOF
}

# settings.local.json에 권한 추가
add_permission() {
    local _file="$1" _perm="$2"
    python3 - "$_file" "$_perm" <<'PYEOF'
import json, sys
fpath, perm = sys.argv[1], sys.argv[2]
try:
    with open(fpath) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError, ValueError):
    data = {'permissions': {'allow': []}}

allows = data.setdefault('permissions', {}).setdefault('allow', [])
if perm not in allows:
    allows.append(perm)
    with open(fpath, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f'추가됨: {perm}')
else:
    print(f'이미 존재: {perm}')
PYEOF
}

# Codex 인증 확인 (auth.json 또는 CODEX_API_KEY)
check_codex_token() {
    # 방법 1: API 키 환경변수
    if [ -n "${CODEX_API_KEY:-}" ]; then
        return 0
    fi
    # 방법 2: OAuth auth.json
    if [ ! -f "$CODEX_AUTH" ]; then
        return 1
    fi
    python3 - "$CODEX_AUTH" <<'PYEOF'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    if 'access_token' in data and len(data['access_token']) > 10:
        sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(1)
PYEOF
}

# --- 메인 ---
echo "=== MCP 서버 설정 확인 ==="
echo ""

# 1. Codex MCP
if [ "$CHECK_TARGET" = "all" ] || [ "$CHECK_TARGET" = "codex" ]; then
    echo "[Codex MCP]"

    # 1a. MCP 서버 등록
    if json_has_key "$CLAUDE_JSON" "codex-agent"; then
        print_status "MCP 서버 등록" "OK" "codex-agent"
    else
        if $CHECK_ONLY; then
            print_status "MCP 서버 등록" "NEED" "codex-agent 미등록"
        else
            echo "  Codex MCP 서버 등록 중..."
            if claude mcp add codex-agent -- npx @openai/codex mcp-server 2>/dev/null; then
                print_status "MCP 서버 등록" "OK" "codex-agent 등록 완료"
            else
                print_status "MCP 서버 등록" "FAIL" "수동 등록 필요: claude mcp add codex-agent -- npx @openai/codex mcp-server"
            fi
        fi
    fi

    # 1b. Codex 로그인 상태
    if check_codex_token; then
        if [ -n "${CODEX_API_KEY:-}" ]; then
            print_status "로그인 상태" "OK" "CODEX_API_KEY 설정됨"
        else
            print_status "로그인 상태" "OK" "~/.codex/auth.json 유효"
        fi
    else
        if $CHECK_ONLY; then
            print_status "로그인 상태" "NEED" "로그인 필요"
        else
            echo "  Codex 로그인이 필요합니다."
            echo "  ChatGPT Pro/Plus 구독이 필요합니다."
            echo ""
            echo "  방법 1 — 브라우저 OAuth 로그인 (ChatGPT 구독):"
            echo "    npx @openai/codex --login"
            echo ""
            echo "  방법 2 — API 키 (별도 과금):"
            echo "    export CODEX_API_KEY=sk-..."
            echo ""
            print_status "로그인 상태" "NEED" "위 방법 중 하나로 로그인하세요"
        fi
    fi

    echo ""
fi

# 2. Gemini MCP
if [ "$CHECK_TARGET" = "all" ] || [ "$CHECK_TARGET" = "gemini" ]; then
    echo "[Gemini MCP]"

    # 2a. MCP 서버 등록
    if json_has_key "$CLAUDE_JSON" "gemini"; then
        print_status "MCP 서버 등록" "OK" "gemini"
    else
        if $CHECK_ONLY; then
            print_status "MCP 서버 등록" "NEED" "gemini 미등록"
        else
            echo "  Gemini MCP 서버 등록 중..."
            if claude mcp add gemini -- npx -y gemini-mcp-tool 2>/dev/null; then
                print_status "MCP 서버 등록" "OK" "gemini 등록 완료"
            else
                print_status "MCP 서버 등록" "FAIL" "수동 등록 필요: claude mcp add gemini -- npx -y gemini-mcp-tool"
            fi
        fi
    fi

    # 2b. Gemini API 키
    if [ -n "${GOOGLE_AI_API_KEY:-}" ] || [ -n "${GEMINI_API_KEY:-}" ]; then
        print_status "API 키" "OK" "환경변수 설정됨"
    else
        if $CHECK_ONLY; then
            print_status "API 키" "NEED" "GOOGLE_AI_API_KEY 미설정"
        else
            echo "  Gemini API 키가 필요합니다."
            echo "  발급: https://aistudio.google.com/apikey"
            echo "  설정: export GOOGLE_AI_API_KEY=AI..."
            echo ""
            print_status "API 키" "NEED" "위 URL에서 API 키를 발급하세요"
        fi
    fi

    echo ""
fi

# 3. settings.local.json 권한
if [ "$CHECK_TARGET" = "all" ]; then
    echo "[권한 설정] $SETTINGS_LOCAL"

    for perm in "mcp__codex-agent__codex" "mcp__codex-agent__codex-reply" "mcp__gemini__ask-gemini"; do
        if has_permission "$SETTINGS_LOCAL" "$perm"; then
            print_status "$perm" "OK"
        else
            if $CHECK_ONLY; then
                print_status "$perm" "NEED" "권한 누락"
            else
                add_permission "$SETTINGS_LOCAL" "$perm"
                print_status "$perm" "OK" "추가됨"
            fi
        fi
    done

    echo ""
fi

# 결과 요약
echo "=== 결과 ==="
if [ "$STATUS_NEED" -eq 0 ]; then
    echo "  모든 MCP 설정이 정상입니다."
    exit 0
else
    if $CHECK_ONLY; then
        echo "  설정이 필요합니다. /pdf-chunker:setup 을 실행하세요."
    else
        echo "  일부 항목이 수동 설정을 필요로 합니다. 위 안내를 따라주세요."
    fi
    exit 1
fi
