#!/usr/bin/env python3
"""PDF 파일을 10페이지씩 분할하는 스크립트.

11페이지 이상인 PDF를 10페이지 단위로 분할합니다.
파일 경로 또는 폴더 경로를 받을 수 있습니다.

사용법:
    # 단일 PDF 파일
    python3 split_pdf.py input.pdf

    # 폴더 내 모든 PDF
    python3 split_pdf.py /path/to/folder

    # 출력 디렉토리 지정
    python3 split_pdf.py input.pdf -o /output/dir

    # 분할 크기 지정 (기본 10)
    python3 split_pdf.py input.pdf --chunk 20
"""

import argparse
import glob
import math
import os
import sys

import fitz  # PyMuPDF


def split_pdf(pdf_path, output_dir=None, chunk_size=10, verbose=False):
    """PDF를 chunk_size 페이지씩 분할한다.

    Args:
        pdf_path: PDF 파일 경로
        output_dir: 출력 디렉토리 (None이면 원본과 같은 디렉토리)
        chunk_size: 분할 단위 (기본 10)
        verbose: 상세 출력

    Returns:
        생성된 분할 파일 경로 리스트. 분할 불필요시 원본 경로 리스트.
    """
    doc = fitz.open(pdf_path)
    total = doc.page_count

    if total <= chunk_size:
        if verbose:
            print(f"  {total}페이지 - 분할 불필요")
        doc.close()
        return [pdf_path]

    if output_dir is None:
        output_dir = os.path.dirname(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    num_files = math.ceil(total / chunk_size)
    created = []

    for i in range(num_files):
        start = i * chunk_size
        end = min(start + chunk_size - 1, total - 1)

        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start, to_page=end)

        filename = f"{basename}_{start + 1:04d}-{end + 1:04d}.pdf"
        filepath = os.path.join(output_dir, filename)
        new_doc.save(filepath)
        new_doc.close()
        created.append(filepath)

        if verbose:
            print(f"  {filename} (페이지 {start + 1}-{end + 1})")

    doc.close()
    return created


def main():
    parser = argparse.ArgumentParser(
        description="PDF를 10페이지씩 분할합니다."
    )
    parser.add_argument(
        "input",
        help="PDF 파일 경로 또는 폴더 경로"
    )
    parser.add_argument(
        "-o", "--output",
        help="출력 디렉토리 (기본: 원본과 같은 위치)"
    )
    parser.add_argument(
        "--chunk", type=int, default=10,
        help="분할 단위 페이지 수 (기본: 10)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="상세 출력"
    )

    args = parser.parse_args()

    # 입력이 폴더인지 파일인지 판단
    if os.path.isdir(args.input):
        pdf_files = sorted(glob.glob(os.path.join(args.input, "*.pdf")))
        if not pdf_files:
            print(f"폴더에 PDF 파일이 없습니다: {args.input}", file=sys.stderr)
            sys.exit(1)
    elif os.path.isfile(args.input):
        pdf_files = [args.input]
    else:
        print(f"경로를 찾을 수 없습니다: {args.input}", file=sys.stderr)
        sys.exit(1)

    total_created = 0
    total_skipped = 0

    for pdf_path in pdf_files:
        if args.verbose:
            print(f"[처리] {os.path.basename(pdf_path)}")

        result = split_pdf(
            pdf_path, output_dir=args.output,
            chunk_size=args.chunk, verbose=args.verbose
        )

        if len(result) == 1 and result[0] == pdf_path:
            total_skipped += 1
        else:
            total_created += len(result)

    print(f"\n완료: {len(pdf_files)}개 PDF 처리")
    print(f"  분할 생성: {total_created}개 파일")
    print(f"  분할 불필요: {total_skipped}개 파일")


if __name__ == "__main__":
    main()
