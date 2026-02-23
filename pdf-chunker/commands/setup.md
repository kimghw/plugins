---
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# PDF → 청크 JSON 플러그인 초기 설정

새 프로젝트에서 플러그인을 처음 사용할 때 경로와 권한을 대화형으로 설정합니다.

## 실행 순서

### 1단계: 현재 환경 확인

```bash
echo "=== 현재 환경 ==="
echo "프로젝트 디렉토리: $CLAUDE_PROJECT_DIR"
echo "플러그인 디렉토리: $CLAUDE_PLUGIN_DIR"
echo "사용자: $(whoami)"
echo "홈 디렉토리: $HOME"
echo ""

# 기존 설정 파일 확인
if [ -f "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env" ]; then
    echo "=== 기존 설정 발견 ==="
    cat "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"
    echo ""
fi
```

### 2단계: 사용자에게 경로 설정 질문

AskUserQuestion으로 다음을 물어본다:

**질문 1 — PDF 원본 경로**
- header: "PDF 경로"
- question: "변환할 PDF 파일들이 있는 디렉토리 경로를 알려주세요. (분할된 chunk PDF가 있는 폴더)"
- options:
  - `$CLAUDE_PROJECT_DIR/pdf-source/chunks` — "프로젝트 내 기본 경로"
  - `$HOME/pdf-source/chunks` — "홈 디렉토리 기준"
- (사용자가 Other로 직접 경로를 입력할 수도 있음)

**질문 2 — 마크다운 출력 경로**
- header: "출력 경로"
- question: "변환된 마크다운 파일을 저장할 디렉토리 경로를 알려주세요."
- options:
  - `$CLAUDE_PROJECT_DIR/pdf-source/output` — "프로젝트 내 기본 경로"
  - `$HOME/pdf-source/output` — "홈 디렉토리 기준"
- (사용자가 Other로 직접 경로를 입력할 수도 있음)

**질문 3 — 공유 큐 경로**
- header: "큐 경로"
- question: "공유 큐 디렉토리 경로를 알려주세요. 여러 사용자/터미널이 같은 큐를 공유합니다."
- options:
  - `$CLAUDE_PROJECT_DIR/.queue` — "프로젝트 루트 .queue/ (권장)"
  - `$HOME/.queue` — "홈 디렉토리 기준"
- (사용자가 Other로 직접 경로를 입력할 수도 있음)

### 3단계: 설정 파일 생성

사용자 응답을 바탕으로 `.claude/pdf-queue.env` 파일을 생성한다.
이 파일은 config.sh가 자동으로 로드한다.

```bash
mkdir -p "$CLAUDE_PROJECT_DIR/.claude"

cat > "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env" << EOF
# PDF → 마크다운 플러그인 경로 설정
# 생성: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# 사용자: $(whoami)@$(hostname -s)
#
# config.sh가 이 파일을 자동으로 로드합니다.
# 경로를 변경하려면 이 파일을 직접 수정하세요.

PDF_DIR="${사용자가_선택한_PDF_경로}"
MD_DIR="${사용자가_선택한_MD_경로}"
QUEUE_DIR="${사용자가_선택한_QUEUE_경로}"
EOF

echo "설정 파일 생성 완료: $CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"
cat "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"
```

### 4단계: 경로 존재 확인 및 생성

```bash
source "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"

for dir in "$PDF_DIR" "$MD_DIR" "$MD_DIR/images" "$QUEUE_DIR"; do
    if [ ! -d "$dir" ]; then
        echo "디렉토리 생성: $dir"
        mkdir -p "$dir"
    else
        echo "확인 완료: $dir"
    fi
done
```

### 5단계: 권한 설정

`.claude/settings.local.json`이 없으면 자동 생성한다.

```bash
if [ ! -f "$CLAUDE_PROJECT_DIR/.claude/settings.local.json" ]; then
    cat > "$CLAUDE_PROJECT_DIR/.claude/settings.local.json" << 'SETTINGS'
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "WebFetch(*)",
      "WebSearch(*)",
      "Task(*)",
      "Glob(*)",
      "Grep(*)"
    ]
  }
}
SETTINGS
    echo "권한 설정 완료: $CLAUDE_PROJECT_DIR/.claude/settings.local.json"
else
    echo "기존 권한 설정 유지: $CLAUDE_PROJECT_DIR/.claude/settings.local.json"
fi
```

### 6단계: 글로벌 alias 설정

모든 사용자가 `claude-kgc` 명령으로 플러그인을 포함하여 실행할 수 있도록 시스템 전역 alias를 등록한다.
이미 등록되어 있으면 건너뛴다.

먼저 플러그인 경로를 탐색하여 사용자에게 확인한다.

```bash
ALIAS_FILE="/etc/profile.d/claude-kgc.sh"

# 플러그인 경로 후보 탐색 (우선순위 순)
PLUGIN_CANDIDATES=()

# 1. CLAUDE_PLUGIN_DIR 환경변수 (캐시 경로일 수 있음)
[ -n "$CLAUDE_PLUGIN_DIR" ] && [ -f "$CLAUDE_PLUGIN_DIR/.claude-plugin/plugin.json" ] && \
    PLUGIN_CANDIDATES+=("$CLAUDE_PLUGIN_DIR")

# 2. 프로젝트 내 플러그인 소스 디렉토리
for candidate in \
    "$CLAUDE_PROJECT_DIR/plugins/pdf-chunker" \
    "$(pwd)/plugins/pdf-chunker"; do
    [ -f "$candidate/.claude-plugin/plugin.json" ] && PLUGIN_CANDIDATES+=("$candidate")
done

# 3. 플러그인 캐시 디렉토리에서 최신 버전 검색
CACHE_BASE="$HOME/.claude/plugins/cache/kimghw-plugins/pdf-chunker"
if [ -d "$CACHE_BASE" ]; then
    LATEST_CACHE=$(ls -d "$CACHE_BASE"/*/ 2>/dev/null | sort -V | tail -1)
    [ -n "$LATEST_CACHE" ] && [ -f "${LATEST_CACHE}.claude-plugin/plugin.json" ] && \
        PLUGIN_CANDIDATES+=("${LATEST_CACHE%/}")
fi

# 4. 기존 alias 파일에서 경로 추출
if [ -f "$ALIAS_FILE" ]; then
    EXISTING_PATH=$(grep -oP "(?<=--plugin-dir )[^ '\"]+|(?<=--plugin-dir ')[^']+" "$ALIAS_FILE")
    [ -n "$EXISTING_PATH" ] && [ -f "$EXISTING_PATH/.claude-plugin/plugin.json" ] && \
        PLUGIN_CANDIDATES+=("$EXISTING_PATH")
fi

# 중복 제거
PLUGIN_CANDIDATES=($(printf '%s\n' "${PLUGIN_CANDIDATES[@]}" | sort -u))

echo "=== 플러그인 경로 탐색 결과 ==="
for i in "${!PLUGIN_CANDIDATES[@]}"; do
    p="${PLUGIN_CANDIDATES[$i]}"
    ver=$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$p/.claude-plugin/plugin.json" 2>/dev/null | grep -o '"[^"]*"$' | tr -d '"')
    echo "  [$((i+1))] $p (v${ver:-?})"
done

if [ -f "$ALIAS_FILE" ]; then
    echo ""
    echo "기존 alias 파일: $ALIAS_FILE"
    cat "$ALIAS_FILE"
fi
```

탐색 결과를 보여준 후, AskUserQuestion으로 사용할 경로를 확인한다:
- header: "플러그인 경로"
- question: "글로벌 alias에 등록할 플러그인 경로를 선택하세요."
- options: 탐색된 후보들을 나열 (소스 디렉토리 우선 권장)
- 사용자가 Other로 직접 입력 가능

사용자가 선택한 경로로 alias를 등록한다:

```bash
PLUGIN_PATH="${사용자가_선택한_경로}"

# 선택한 경로 검증
if [ ! -f "$PLUGIN_PATH/.claude-plugin/plugin.json" ]; then
    echo "[ERROR] $PLUGIN_PATH 에 plugin.json이 없습니다. 올바른 플러그인 경로인지 확인하세요."
else
    echo "글로벌 alias 등록: claude-kgc → $PLUGIN_PATH"
    sudo tee "$ALIAS_FILE" > /dev/null << EOF
alias claude-kgc='claude --plugin-dir $PLUGIN_PATH'
EOF
    echo "등록 완료. 새 터미널에서 'claude-kgc'로 실행 가능합니다."
fi
```

### 7단계: 기본 설정 검증

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
echo ""
echo "=== 기본 설정 확인 ==="
echo "PDF 디렉토리:    $PDF_DIR"
echo "마크다운 출력:    $MD_DIR"
echo "공유 큐:         $QUEUE_DIR"
echo ""
```

### 8단계: MCP 서버 설정

Stage 2 검증에 필요한 MCP 서버(Codex, Gemini)를 자동 설정합니다.

```bash
bash "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/setup_mcp.sh"
```

이 스크립트가 자동으로 수행하는 작업:

1. **Codex MCP 서버 등록** — `~/.claude.json`에 codex-agent 미등록 시 자동 등록
   - 등록 명령: `claude mcp add codex-agent -- npx @openai/codex mcp-server`
2. **Codex 로그인 확인** — `~/.codex/auth.json` 토큰 유효성 확인
   - 미로그인 시 안내: ChatGPT Pro/Plus 구독 필요, `npx @openai/codex --login` 실행
   - API 키 방식: `export CODEX_API_KEY=sk-...` (별도 과금)
3. **Gemini MCP 서버 등록** — `~/.claude.json`에 gemini 미등록 시 자동 등록
   - 등록 명령: `claude mcp add gemini -- npx -y gemini-mcp-tool`
4. **Gemini API 키 확인** — `GOOGLE_AI_API_KEY` 환경변수 확인
   - 미설정 시 발급 안내: https://aistudio.google.com/apikey
5. **MCP 권한 자동 추가** — `settings.local.json`에 아래 권한이 없으면 자동 추가:
   - `mcp__codex-agent__codex`
   - `mcp__codex-agent__codex-reply`
   - `mcp__gemini__ask-gemini`

스크립트 실행 결과를 확인하고, NEED_ACTION 항목이 있으면 사용자에게 안내한다.

### 9단계: 다사용자 환경 확인

AskUserQuestion으로 물어본다:

**질문 — 다사용자 환경**
- header: "다사용자"
- question: "같은 PC에서 다른 사용자도 이 플러그인을 사용하나요?"
- options:
  - "아니요 (나만 사용)" — "이 단계를 건너뜁니다"
  - "예 (다른 사용자도 사용)" — "공유 디렉토리 그룹 권한을 설정합니다"

**"예" 선택 시:**

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"

# 공유 대상 디렉토리에 그룹 쓰기 + setgid 권한 부여
for shared_dir in "$PDF_DIR" "$MD_DIR" "$QUEUE_DIR"; do
    if [ -d "$shared_dir" ]; then
        chmod -R g+rwX "$shared_dir" 2>/dev/null
        find "$shared_dir" -type d -exec chmod g+s {} \; 2>/dev/null
    fi
done

CURRENT_GROUP=$(id -gn)
echo ""
echo "=== 다사용자 설정 완료 ==="
echo "현재 사용자 그룹: $CURRENT_GROUP"
echo ""
echo "다른 사용자를 같은 그룹에 추가하세요:"
echo "  sudo usermod -aG $CURRENT_GROUP <사용자명>"
echo ""
echo "다른 사용자는 아래 순서로 설정:"
echo "  1. cd $CLAUDE_PROJECT_DIR"
echo "  2. claude --plugin-dir $CLAUDE_PLUGIN_DIR"
echo "  3. /pdf-chunker:setup    # 각자의 MCP/권한 설정"
echo "  4. /pdf-chunker start    # 작업 시작"
echo ""
echo "상세 협업 설정: /pdf-chunker:cowork"
```

**"아니요" 선택 시:** 이 단계를 건너뛴다.

### 10단계: 최종 확인

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
echo ""
echo "=== 최종 설정 확인 ==="
echo "PDF 디렉토리:    $PDF_DIR"
echo "마크다운 출력:    $MD_DIR"
echo "이미지 디렉토리:  $IMG_DIR"
echo "공유 큐:         $QUEUE_DIR"
echo "인스턴스 ID:     $INSTANCE_ID"
echo ""

# MCP 상태 요약
bash "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/setup_mcp.sh" --check-only
echo ""

# PDF 파일 수 확인
pdf_count=$(ls "$PDF_DIR"/*.pdf 2>/dev/null | wc -l || echo 0)
echo "PDF 파일 수: ${pdf_count}개"

if [ "$pdf_count" -gt 0 ]; then
    echo ""
    echo "설정 완료! 다음 명령으로 시작하세요:"
    echo "  /pdf-chunker init    # 큐 초기화"
    echo "  /pdf-chunker start   # 변환 시작"
else
    echo ""
    echo "설정 완료! PDF 파일을 $PDF_DIR 에 넣은 후:"
    echo "  /pdf-chunker init    # 큐 초기화"
    echo "  /pdf-chunker start   # 변환 시작"
fi
```

## 참고

- 설정 파일 위치: `$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env`
- 설정을 변경하려면 이 파일을 직접 수정하거나 `/pdf-chunker:setup`을 다시 실행
- `.claude/pdf-queue.env`는 `.gitignore`에 추가하는 것을 권장 (사용자별 경로가 다를 수 있음)
- 여러 사용자가 같은 프로젝트를 사용할 때는 `/pdf-chunker:cowork`를 참고
- MCP 설정만 다시 실행: `bash "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/scripts/setup_mcp.sh"`
