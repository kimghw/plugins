#!/bin/bash
# PDF → 청크 JSON 변환 플러그인 설정
# 새 프로젝트에서 사용 시 이 파일의 경로만 수정하면 됩니다.

# 프로젝트 루트 (자동 감지)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"

# 플러그인 루트 (자동 감지)
PLUGIN_DIR="${CLAUDE_PLUGIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# PDF/마크다운 경로 (환경 변수 또는 .env 파일로 override 가능)
# .env 파일이 있으면 로드 (프로젝트 루트 또는 큐 디렉토리)
for _envfile in "$PROJECT_DIR/.claude/pdf-queue.env" "$PROJECT_DIR/.env.pdf-queue"; do
    if [ -f "$_envfile" ]; then
        set -a
        source "$_envfile"
        set +a
        break
    fi
done

PDF_DIR="${PDF_DIR:-/home/kimghw/kgc/pdf-source/chunks}"
MD_DIR="${MD_DIR:-/home/kimghw/kgc/pdf-source/output}"  # 청크 JSON 출력 디렉토리 (레거시 변수명 유지)
IMG_DIR="${IMG_DIR:-$MD_DIR/images}"

# --- 공유 큐 설정 (디렉토리 기반, 절대 경로) ---
# 여러 구독/계정에서 같은 큐를 공유하기 위해 절대 경로 사용
QUEUE_DIR="${QUEUE_DIR:-/home/kimghw/kgc/.queue}"
QUEUE_PENDING="$QUEUE_DIR/pending"
QUEUE_PROCESSING="$QUEUE_DIR/processing"
QUEUE_DONE="$QUEUE_DIR/done"
QUEUE_FAILED="$QUEUE_DIR/failed"

# 레거시 큐 파일 (마이그레이션용)
QUEUE_FILE_LEGACY="$PROJECT_DIR/.claude/pdf-queue.txt"

# 인스턴스 식별자 (세션 고정 UUID)
# config.sh를 source할 때마다 PID가 바뀌는 문제 방지
# 세션당 한 번 생성되어 /tmp에 저장됨
_INSTANCE_ID_FILE="/tmp/.claude-queue-instance-${CLAUDE_SESSION_ID:-$$}"
if [ -f "$_INSTANCE_ID_FILE" ]; then
    INSTANCE_ID="$(cat "$_INSTANCE_ID_FILE")"
else
    INSTANCE_ID="$(hostname -s)_$(date +%s)_$(head -c8 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    echo "$INSTANCE_ID" > "$_INSTANCE_ID_FILE"
fi

# stale 작업 기준 (초, 기본 30분)
STALE_THRESHOLD=1800

# 리스 기간 (초, 기본 45분 — STALE_THRESHOLD보다 여유 있게)
LEASE_DURATION=2700

# 스킬 디렉토리
SKILL_DIR="$PLUGIN_DIR/skills/pdf-chunker"

# 큐 관리 스크립트
QUEUE_SCRIPT="$SKILL_DIR/scripts/queue_manager.sh"
