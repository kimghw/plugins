---
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# 협업 세팅 — 다른 사용자/구독이 동일 큐로 병렬 작업

다른 Claude 구독, 다른 Linux 사용자, 또는 다른 홈 디렉토리를 가진 터미널에서
동일한 플러그인과 공유 큐를 사용하여 함께 작업할 수 있도록 설정합니다.

## 전제 조건

- 모든 참여자가 **동일한 플러그인 디렉토리**에 접근 가능
- **PDF 소스, 마크다운 출력, 큐 디렉토리**가 공유 경로에 있어야 함
- 각자의 Claude 세션에서 `claude --plugin-dir <플러그인경로>`로 실행

## 실행 순서

### 1단계: 현재 환경 진단

```bash
echo "=== 현재 사용자 환경 ==="
echo "사용자:         $(whoami)"
echo "홈 디렉토리:    $HOME"
echo "프로젝트:       $CLAUDE_PROJECT_DIR"
echo "플러그인:       $CLAUDE_PLUGIN_DIR"
echo ""

# 기존 설정 확인
if [ -f "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env" ]; then
    echo "=== 기존 pdf-queue.env 발견 ==="
    cat "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"
    echo ""
fi

# config.sh 현재 값 확인
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"
echo "=== config.sh 로드 결과 ==="
echo "PDF_DIR:     $PDF_DIR"
echo "MD_DIR:      $MD_DIR"
echo "QUEUE_DIR:   $QUEUE_DIR"
echo "INSTANCE_ID: $INSTANCE_ID"
echo ""

# 경로 접근 가능 여부 확인
for dir_name in PDF_DIR MD_DIR QUEUE_DIR; do
    dir_val="${!dir_name}"
    if [ -d "$dir_val" ]; then
        if [ -w "$dir_val" ]; then
            echo "[OK] $dir_name ($dir_val) — 접근 및 쓰기 가능"
        else
            echo "[WARNING] $dir_name ($dir_val) — 읽기 전용 (쓰기 불가)"
        fi
    else
        echo "[MISSING] $dir_name ($dir_val) — 디렉토리 없음"
    fi
done
```

### 2단계: 사용자에게 협업 시나리오 질문

AskUserQuestion으로 물어본다:

**질문 1 — 협업 시나리오**
- header: "협업 유형"
- question: "어떤 환경에서 협업하려고 하나요?"
- options:
  - "같은 PC, 다른 터미널" — "동일 사용자가 여러 Claude 세션을 열어 병렬 처리 (가장 일반적)"
  - "같은 PC, 다른 사용자" — "Linux 사용자 계정이 다름 (sudo 또는 공유 디렉토리 필요)"
  - "다른 PC, 공유 저장소" — "NFS, SMB, 클라우드 동기화 등으로 파일 공유"

**질문 2 — 공유 경로 확인**
- header: "공유 경로"
- question: "모든 참여자가 접근할 수 있는 공유 디렉토리 경로를 알려주세요. PDF, 출력, 큐가 이 경로 아래에 위치합니다."
- options:
  - "$CLAUDE_PROJECT_DIR" — "현재 프로젝트 디렉토리 (권장)"
  - "/shared" — "별도 공유 디렉토리"
- (사용자가 Other로 직접 입력 가능)

### 3단계: 공유 경로 기반 설정 파일 생성

사용자의 응답에 따라 `.claude/pdf-queue.env`를 생성한다.

핵심 원칙: **모든 참여자가 동일한 절대 경로**로 PDF_DIR, MD_DIR, QUEUE_DIR에 접근해야 한다.

```bash
mkdir -p "$CLAUDE_PROJECT_DIR/.claude"

SHARED_BASE="${사용자가_지정한_공유_경로}"

cat > "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env" << EOF
# PDF → 마크다운 협업 설정
# 생성: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# 설정자: $(whoami)@$(hostname -s)
#
# 이 파일은 모든 참여자가 공유합니다.
# 모든 경로는 절대 경로여야 하며, 모든 참여자가 접근 가능해야 합니다.

PDF_DIR="${SHARED_BASE}/pdf-source/chunks"
MD_DIR="${SHARED_BASE}/pdf-source/output"
QUEUE_DIR="${SHARED_BASE}/.queue"
EOF

echo "설정 파일 생성: $CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"
cat "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"
```

### 4단계: 디렉토리 생성 및 권한 설정

```bash
source "$CLAUDE_PROJECT_DIR/.claude/pdf-queue.env"

for dir in "$PDF_DIR" "$MD_DIR" "$MD_DIR/images" \
           "$QUEUE_DIR" "$QUEUE_DIR/pending" "$QUEUE_DIR/processing" \
           "$QUEUE_DIR/done" "$QUEUE_DIR/failed"; do
    mkdir -p "$dir" 2>/dev/null
done

echo "디렉토리 생성 완료"
```

**"같은 PC, 다른 사용자" 시나리오인 경우**, 자동으로 공유 디렉토리에 그룹 쓰기 권한을 설정한다.
현재 사용자와 협업 사용자가 같은 그룹에 속해 있어야 한다.

```bash
# 공유 대상 디렉토리들에 그룹 쓰기 + sticky 권한 부여
chmod -R g+rwX "$SHARED_BASE/pdf-source" "$SHARED_BASE/.queue" 2>/dev/null

# 새로 생성되는 파일/디렉토리도 그룹 쓰기 가능하도록 setgid 설정
find "$SHARED_BASE/pdf-source" "$SHARED_BASE/.queue" -type d -exec chmod g+s {} \; 2>/dev/null

echo "그룹 쓰기 권한 설정 완료"
echo ""

# 현재 그룹 확인 및 안내
CURRENT_GROUP=$(id -gn)
echo "현재 사용자 그룹: $CURRENT_GROUP"
echo "협업 사용자도 같은 그룹에 속해야 합니다."
echo "확인: id <사용자명>"
echo "추가: sudo usermod -aG $CURRENT_GROUP <사용자명>"
```

**"같은 PC, 같은 사용자" 또는 "다른 PC" 시나리오인 경우**, 그룹 권한 설정을 건너뛴다.

### 5단계: 권한 설정 (settings.local.json)

참여자별로 각자의 `.claude/settings.local.json`이 필요하다.
이 파일은 git에 포함되지 않으므로 각자 생성해야 한다.

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
    echo "권한 설정 완료"
else
    echo "기존 권한 설정 유지"
fi
```

### 6단계: 검증 및 안내

```bash
source "$CLAUDE_PLUGIN_DIR/skills/pdf-chunker/config.sh"

echo ""
echo "=== 협업 설정 완료 ==="
echo ""
echo "PDF 디렉토리:    $PDF_DIR"
echo "마크다운 출력:    $MD_DIR"
echo "공유 큐:         $QUEUE_DIR"
echo "내 인스턴스 ID:  $INSTANCE_ID"
echo ""

# 큐 상태 확인
if [ -d "$QUEUE_DIR/pending" ]; then
    pending=$(ls "$QUEUE_DIR/pending/"*.task 2>/dev/null | wc -l || echo 0)
    processing=$(ls "$QUEUE_DIR/processing/"*.task 2>/dev/null | wc -l || echo 0)
    done_count=$(ls "$QUEUE_DIR/done/"*.task 2>/dev/null | wc -l || echo 0)
    echo "큐 현황: 대기 ${pending} / 작업중 ${processing} / 완료 ${done_count}"
    echo ""
fi
```

최종적으로 다음 안내 메시지를 출력한다:

```
=== 다른 참여자 안내 ===

다른 터미널/사용자에게 아래 내용을 전달하세요:

1. 프로젝트 디렉토리로 이동:
   cd {프로젝트_경로}

2. 플러그인 포함하여 Claude 실행:
   claude --plugin-dir {플러그인_경로}

3. 초기 설정 (처음 1회):
   /pdf-chunker:setup

4. 작업 시작:
   /pdf-chunker status    # 현황 확인
   /pdf-chunker start     # 변환 시작

각 참여자는 서로 다른 작업을 자동으로 할당받아 병렬 처리합니다.
동일 작업이 중복 할당되지 않으므로 안심하고 동시에 실행하세요.
```

## 문제 해결

### "경로에 접근할 수 없습니다"
→ 공유 디렉토리의 퍼미션 확인: `ls -la {경로}`
→ 다른 사용자인 경우: `chmod g+rwX` 또는 ACL 설정 필요

### "INSTANCE_ID가 충돌합니다"
→ 세션 고정 UUID를 사용하므로 정상적으로는 충돌하지 않음
→ `/tmp/.claude-queue-instance-*` 파일 삭제 후 재시작

### "다른 인스턴스의 작업을 수정할 수 없습니다"
→ 소유자 검증이 활성화되어 있음 (정상 동작)
→ 강제 실행 필요 시: `bash queue_manager.sh complete <name> --force`

### "설정이 반영되지 않습니다"
→ `.claude/pdf-queue.env` 파일이 프로젝트 루트의 `.claude/` 안에 있는지 확인
→ Claude Code를 재시작하면 새 설정이 적용됨
