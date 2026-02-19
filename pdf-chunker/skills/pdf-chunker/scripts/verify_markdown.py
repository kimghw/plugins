#!/usr/bin/env python3
"""
PDF-Markdown 검증 스크립트

PDF에서 추출한 텍스트 뭉치(문장/단어)가 마크다운에 포함되어 있는지 확인합니다.
누락된 항목만 리포트하여 Claude로 재검토할 수 있게 합니다.
"""

import fitz  # PyMuPDF
import re
import sys
import argparse
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Set


@dataclass
class MissingItem:
    """누락된 항목"""
    text: str
    page_num: int
    item_type: str  # 'sentence', 'phrase', 'keyword'


@dataclass
class VerificationReport:
    """검증 결과 리포트"""
    pdf_file: str
    md_file: str
    total_chunks: int = 0
    found_chunks: int = 0
    missing_items: List[MissingItem] = field(default_factory=list)

    @property
    def coverage_rate(self) -> float:
        if self.total_chunks == 0:
            return 100.0
        return (self.found_chunks / self.total_chunks) * 100

    def to_dict(self) -> dict:
        return {
            'pdf_file': self.pdf_file,
            'md_file': self.md_file,
            'total_chunks': self.total_chunks,
            'found_chunks': self.found_chunks,
            'coverage_rate': round(self.coverage_rate, 2),
            'missing_count': len(self.missing_items),
            'missing_items': [
                {
                    'text': m.text,
                    'page': m.page_num,
                    'type': m.item_type
                }
                for m in self.missing_items
            ]
        }


class MarkdownVerifier:
    """마크다운 검증 클래스 - 단어/문장 포함 여부 확인"""

    # 무시할 패턴 (페이지 번호, 머리글/바닥글 등)
    IGNORE_PATTERNS = [
        r'^- [ivx]+ -$',           # 로마 숫자 페이지 번호
        r'^- \d+ -$',              # 숫자 페이지 번호
        r'^\d+$',                   # 단독 숫자
        r'^선급 및 강선규칙 2025$',  # 머리글
        r'^선급및강선규칙2025$',     # 머리글 (공백 없음)
        r'^1 편 \d+ 장$',           # 머리글
        r'^\d+ 편.+검사$',          # 머리글 (1 편선급등록및검사)
        r'^\d+ 편\d+ 장$',          # 머리글 (1 편1 장)
        r'^\d+ 장.+$',              # 머리글 (1 장선급등록)
        r'^[ivx]+$',                # 로마 숫자만
        r'^\.+$',                   # 점만 있는 줄 (목차)
        r'^·+$',                    # 가운데점
        r'^RA-\d+-K$',              # 문서번호
        r'^한\s*국\s*선\s*급$',      # 한국선급
        r'^\d+\s*편\s*부록',          # 머리글 (1 편부록1-7)
        r'^부록\d+-\d+',              # 머리글 (부록1-12-2 ...)
    ]

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.pdf_dir = self.base_dir / "분할"
        self.md_dir = self.base_dir / "마크다운"

    def extract_pdf_chunks(self, pdf_path: Path) -> List[tuple]:
        """
        PDF에서 의미있는 텍스트 뭉치 추출

        Returns:
            List of (text, page_num, chunk_type) tuples
        """
        chunks = []
        doc = fitz.open(pdf_path)

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")

            # 줄 단위로 분리
            lines = text.split('\n')

            for line in lines:
                line = line.strip()

                # 빈 줄 무시
                if not line:
                    continue

                # 무시할 패턴 체크
                if self._should_ignore(line):
                    continue

                # 너무 짧은 텍스트 (1-2자)는 키워드로 분류
                if len(line) <= 2:
                    # 단독 글자는 무시 (레이아웃 문제)
                    continue

                # 문장인지 구문인지 판단
                if len(line) > 20:
                    chunk_type = 'sentence'
                elif len(line) > 5:
                    chunk_type = 'phrase'
                else:
                    chunk_type = 'keyword'

                chunks.append((line, page_num + 1, chunk_type))

        doc.close()
        return chunks

    def _should_ignore(self, text: str) -> bool:
        """무시해야 할 텍스트인지 확인"""
        for pattern in self.IGNORE_PATTERNS:
            if re.match(pattern, text):
                return True
        return False

    def normalize_text(self, text: str) -> str:
        """텍스트 정규화 (비교용)"""
        # 공백 정규화
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        # 전각 문자를 반각으로
        result = []
        for char in text:
            code = ord(char)
            if code == 0x3000:  # 전각 공백
                result.append(' ')
            elif 0xFF01 <= code <= 0xFF5E:  # 전각 ASCII
                result.append(chr(code - 0xFEE0))
            else:
                result.append(char)

        return ''.join(result).lower()

    def extract_words(self, text: str) -> List[str]:
        """텍스트에서 순수 단어만 추출 (특수문자 제거, 1글자 제외)"""
        # 한글, 영문, 숫자만 단어로 인식, 2글자 이상만
        return [w for w in re.findall(r'[가-힣a-zA-Z0-9]+', text.lower()) if len(w) >= 2]

    def make_trigrams(self, words: List[str]) -> List[str]:
        """연속 3단어 조합(trigram) 생성"""
        if len(words) < 3:
            return []
        return [f"{words[i]} {words[i+1]} {words[i+2]}" for i in range(len(words) - 2)]

    def read_markdown_text(self, md_path: Path) -> str:
        """마크다운 파일 전체 텍스트 읽기 (정규화)"""
        with open(md_path, 'r', encoding='utf-8') as f:
            text = f.read()

        # 마크다운 문법 제거
        text = self._strip_markdown(text)

        return self.normalize_text(text)

    def _strip_markdown(self, text: str) -> str:
        """마크다운 문법 제거"""
        # 이미지/링크
        text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

        # 굵게/기울임
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)

        # 코드
        text = re.sub(r'`([^`]+)`', r'\1', text)

        # 제목/목록 마크
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)

        # 표 구분자
        text = re.sub(r'\|', ' ', text)
        text = re.sub(r'^[-:]+$', '', text, flags=re.MULTILINE)

        # 수평선
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)

        # HTML 주석
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

        return text

    def verify(self, pdf_path: Path, md_path: Path) -> VerificationReport:
        """PDF 텍스트가 마크다운에 포함되어 있는지 확인 (줄 단위 trigram 방식)"""
        report = VerificationReport(
            pdf_file=str(pdf_path.name),
            md_file=str(md_path.name)
        )

        # 마크다운 전체 텍스트에서 단어만 추출 → trigram set 생성
        md_text_raw = self.read_markdown_text(md_path)
        md_words = self.extract_words(md_text_raw)
        md_trigrams = set(self.make_trigrams(md_words))

        # PDF 텍스트 뭉치 추출 (줄 단위, IGNORE 패턴 적용)
        pdf_chunks = self.extract_pdf_chunks(pdf_path)

        # 각 줄에서 단어만 추출 → trigram 생성하여 비교
        for chunk_text, page_num, chunk_type in pdf_chunks:
            words = self.extract_words(chunk_text)

            # 순수 단어 3개 미만이면 스킵
            if len(words) < 3:
                continue

            trigrams = self.make_trigrams(words)
            if not trigrams:
                continue

            report.total_chunks += 1

            # trigram 중 하나라도 마크다운에 있으면 포함된 것으로 판정
            found = any(t in md_trigrams for t in trigrams)

            if found:
                report.found_chunks += 1
            else:
                report.missing_items.append(MissingItem(
                    text=chunk_text,
                    page_num=page_num,
                    item_type=chunk_type
                ))

        return report

    def print_report(self, report: VerificationReport, verbose: bool = False):
        """검증 리포트 출력"""
        print(f"\n{'='*60}")
        print(f"검증 결과: {report.pdf_file}")
        print(f"{'='*60}")
        print(f"총 텍스트 뭉치: {report.total_chunks}개")
        print(f"포함 확인: {report.found_chunks}개")
        print(f"커버리지: {report.coverage_rate:.1f}%")
        print(f"누락 의심: {len(report.missing_items)}개")

        if verbose and report.missing_items:
            print(f"\n[누락 의심 항목] - Claude로 재확인 필요")

            # 페이지별로 그룹화
            by_page = {}
            for item in report.missing_items:
                if item.page_num not in by_page:
                    by_page[item.page_num] = []
                by_page[item.page_num].append(item)

            for page_num in sorted(by_page.keys()):
                print(f"\n  📄 페이지 {page_num}:")
                for item in by_page[page_num][:10]:  # 페이지당 최대 10개
                    print(f"    - [{item.item_type}] {item.text[:60]}{'...' if len(item.text) > 60 else ''}")
                if len(by_page[page_num]) > 10:
                    print(f"    ... 외 {len(by_page[page_num]) - 10}개")

    def verify_single(self, pdf_path: Path, md_path: Path,
                      verbose: bool = True) -> VerificationReport:
        """단일 파일 쌍 검증"""
        if not pdf_path.exists():
            print(f"Error: PDF 파일을 찾을 수 없습니다: {pdf_path}")
            return None

        if not md_path.exists():
            print(f"Error: 마크다운 파일을 찾을 수 없습니다: {md_path}")
            return None

        report = self.verify(pdf_path, md_path)
        self.print_report(report, verbose)
        return report

    def verify_all(self, verbose: bool = False) -> List[VerificationReport]:
        """모든 파일 검증"""
        reports = []
        md_files = sorted(self.md_dir.glob("*.md"))

        if not md_files:
            print(f"Error: 마크다운 파일을 찾을 수 없습니다: {self.md_dir}")
            return reports

        print(f"총 {len(md_files)}개 마크다운 파일 검증 시작\n")

        for i, md_path in enumerate(md_files, 1):
            pdf_path = self.pdf_dir / f"{md_path.stem}.pdf"

            if not pdf_path.exists():
                print(f"[{i}/{len(md_files)}] {md_path.name}: PDF 없음")
                continue

            print(f"[{i}/{len(md_files)}] 검증 중: {md_path.name}")
            report = self.verify(pdf_path, md_path)
            reports.append(report)

            status = "OK" if report.coverage_rate >= 90 else "확인필요"
            print(f"  → 커버리지: {report.coverage_rate:.1f}%, 누락의심: {len(report.missing_items)}개 [{status}]")

        # 요약
        print(f"\n{'='*60}")
        print("전체 검증 요약")
        print(f"{'='*60}")
        total_files = len(reports)
        ok_files = len([r for r in reports if r.coverage_rate >= 90])
        print(f"검증 파일: {total_files}개")
        print(f"양호 (90%+): {ok_files}개")
        print(f"확인 필요: {total_files - ok_files}개")

        return reports

    def export_report(self, reports: List[VerificationReport], output_path: Path):
        """검증 결과를 JSON으로 저장"""
        data = {
            'summary': {
                'total_files': len(reports),
                'ok_files': len([r for r in reports if r.coverage_rate >= 90]),
                'avg_coverage': sum(r.coverage_rate for r in reports) / len(reports) if reports else 0
            },
            'reports': [r.to_dict() for r in reports]
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\n검증 결과 저장: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='PDF 텍스트가 마크다운에 포함되어 있는지 검증합니다.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 단일 파일 검증
  python verify_markdown.py 분할/강선규칙_0001-0010.pdf 마크다운/강선규칙_0001-0010.md

  # 전체 파일 검증
  python verify_markdown.py --all

  # 상세 출력
  python verify_markdown.py --all -v

  # JSON으로 결과 저장
  python verify_markdown.py --all --export report.json
        """
    )

    parser.add_argument('pdf_path', nargs='?', help='검증할 PDF 파일 경로')
    parser.add_argument('md_path', nargs='?', help='검증할 마크다운 파일 경로')
    parser.add_argument('--all', action='store_true', help='마크다운 디렉토리의 모든 파일 검증')
    parser.add_argument('--base-dir', default=None, help='기본 디렉토리 경로')
    parser.add_argument('-v', '--verbose', action='store_true', help='상세 출력')
    parser.add_argument('--export', metavar='FILE', help='검증 결과를 JSON 파일로 저장')

    args = parser.parse_args()

    if args.base_dir:
        base_dir = Path(args.base_dir)
    else:
        base_dir = Path(__file__).parent.parent

    verifier = MarkdownVerifier(base_dir)

    if args.all:
        reports = verifier.verify_all(verbose=args.verbose)
        if args.export and reports:
            verifier.export_report(reports, Path(args.export))
    elif args.pdf_path and args.md_path:
        pdf_path = Path(args.pdf_path)
        md_path = Path(args.md_path)

        if not pdf_path.is_absolute():
            pdf_path = base_dir / pdf_path
        if not md_path.is_absolute():
            md_path = base_dir / md_path

        report = verifier.verify_single(pdf_path, md_path, verbose=args.verbose)

        if args.export and report:
            verifier.export_report([report], Path(args.export))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
