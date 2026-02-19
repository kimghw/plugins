#!/usr/bin/env python3
"""PDF에서 이미지(도면/그림)를 추출하는 스크립트.

PyMuPDF를 사용하여 PDF 내 이미지 오브젝트의 위치를 파악하고,
근접한 이미지 조각들을 그룹핑하여 해당 영역을 고해상도로 렌더링합니다.
벡터 그래픽도 포함되며, 캡션이 있으면 파일명에 반영합니다.

사용법:
    # 단일 PDF
    python3 extract_images.py input.pdf -o output_dir

    # 여러 PDF
    python3 extract_images.py *.pdf -o output_dir

    # 전체 분할 PDF
    python3 extract_images.py --all

    # DPI 지정
    python3 extract_images.py input.pdf -o output_dir --dpi 200
"""

import argparse
import configparser
import glob
import os
import re
import subprocess
import sys

import fitz  # PyMuPDF


def load_config():
    """config.sh에서 경로 설정을 로드한다."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_sh = os.path.join(script_dir, "..", "config.sh")

    if os.path.exists(config_sh):
        try:
            result = subprocess.run(
                ["bash", "-c", f'source "{config_sh}" && echo "PDF_DIR=$PDF_DIR" && echo "MD_DIR=$MD_DIR" && echo "IMG_DIR=$IMG_DIR"'],
                capture_output=True, text=True
            )
            config = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    key, val = line.split("=", 1)
                    config[key] = val
            return config
        except Exception:
            pass
    return {}


def extract_images_from_pdf(pdf_path, output_dir, dpi=300, min_area=5000,
                            gap_threshold=5, caption_search_height=30,
                            verbose=False):
    """PDF에서 이미지를 추출한다.

    Args:
        pdf_path: PDF 파일 경로
        output_dir: 이미지 저장 디렉토리 (하위에 PDF명 서브디렉토리 생성)
        dpi: 렌더링 해상도
        min_area: 최소 이미지 영역 (이하 로고/아이콘 제외)
        gap_threshold: 이미지 조각 간 간격 허용치 (pt)
        caption_search_height: 캡션 검색 높이 (pt)
        verbose: 상세 출력 여부

    Returns:
        추출된 이미지 파일 경로 리스트
    """
    doc = fitz.open(pdf_path)
    basename = os.path.splitext(os.path.basename(pdf_path))[0]

    # 이미지 파일명 충돌 방지: images/<task_name>/ 서브디렉토리 사용
    task_output_dir = os.path.join(output_dir, basename)
    os.makedirs(task_output_dir, exist_ok=True)
    extracted = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        images = page.get_images(full=True)
        if not images:
            continue

        # 각 이미지의 위치(rect) 수집 (로고 크기 제외)
        rects = []
        for img in images:
            xref = img[0]
            img_rects = page.get_image_rects(xref)
            for r in img_rects:
                area = r.width * r.height
                if area < min_area:
                    continue
                rects.append(r)

        if not rects:
            continue

        # y좌표로 정렬 후, 근접한 rect들을 그룹핑
        rects.sort(key=lambda r: (r.y0, r.x0))
        groups = []
        current_group = [rects[0]]

        for i in range(1, len(rects)):
            prev_bottom = max(r.y1 for r in current_group)
            if rects[i].y0 <= prev_bottom + gap_threshold:
                current_group.append(rects[i])
            else:
                groups.append(current_group)
                current_group = [rects[i]]
        groups.append(current_group)

        # 각 그룹을 하나의 클립 영역으로 합쳐서 렌더링
        for gi, group in enumerate(groups):
            x0 = min(r.x0 for r in group)
            y0 = min(r.y0 for r in group)
            x1 = max(r.x1 for r in group)
            y1 = max(r.y1 for r in group)

            margin = 5
            clip = fitz.Rect(x0 - margin, y0 - margin, x1 + margin, y1 + margin)
            clip = clip & page.rect

            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, clip=clip)

            # 캡션 찾기: 클립 영역 바로 아래에서 "그림 X.X.X" 패턴 검색
            caption_rect = fitz.Rect(
                x0 - 50, y1, x1 + 50, y1 + caption_search_height
            )
            caption_rect = caption_rect & page.rect
            caption_text = page.get_text("text", clip=caption_rect).strip()

            caption_match = re.search(
                r'그림\s*(\d+[\.\-]\d+[\.\-]\d+)\s*(.*)', caption_text
            )
            if caption_match:
                fig_num = caption_match.group(1)
                fig_desc = caption_match.group(2).strip()[:40]
                fig_desc = re.sub(r'[/\\:*?"<>|\n\r]', '_', fig_desc)
                fig_desc = fig_desc.strip('_. ')
                if fig_desc:
                    filename = f"그림_{fig_num}_{fig_desc}.png"
                else:
                    filename = f"그림_{fig_num}.png"
            else:
                # 캡션 없는 경우: PDF파일명_페이지_순번
                filename = f"{basename}_p{page_num + 1:02d}_{gi + 1:02d}.png"

            filepath = os.path.join(task_output_dir, filename)
            pix.save(filepath)
            extracted.append(filepath)

            if verbose:
                print(f"  페이지 {page_num + 1}: {filename} "
                      f"({pix.width}x{pix.height}, {len(group)}개 조각)")

    doc.close()
    return extracted


def main():
    config = load_config()
    default_output = config.get("IMG_DIR", "images")
    default_pdf_dir = config.get("PDF_DIR", ".")

    parser = argparse.ArgumentParser(
        description="PDF에서 이미지(도면/그림)를 추출합니다."
    )
    parser.add_argument(
        "pdf_files", nargs="*",
        help="추출할 PDF 파일(들)"
    )
    parser.add_argument(
        "-o", "--output",
        default=default_output,
        help=f"이미지 저장 디렉토리 (기본: {default_output})"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="분할 디렉토리의 모든 PDF 처리"
    )
    parser.add_argument(
        "--dpi", type=int, default=300,
        help="렌더링 해상도 (기본: 300)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="상세 출력"
    )

    args = parser.parse_args()

    if args.all:
        pdf_dir = default_pdf_dir
        pdf_files = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")))
    elif args.pdf_files:
        pdf_files = args.pdf_files
    else:
        parser.print_help()
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)
    total_extracted = 0

    for i, pdf_path in enumerate(pdf_files):
        if not os.path.exists(pdf_path):
            print(f"파일 없음: {pdf_path}", file=sys.stderr)
            continue

        if args.verbose or len(pdf_files) > 1:
            print(f"[{i + 1}/{len(pdf_files)}] {os.path.basename(pdf_path)}")

        extracted = extract_images_from_pdf(
            pdf_path, args.output,
            dpi=args.dpi, verbose=args.verbose
        )
        total_extracted += len(extracted)

        if (i + 1) % 50 == 0:
            print(f"  진행: {i + 1}/{len(pdf_files)} PDF, "
                  f"추출 {total_extracted}개")

    print(f"\n완료: {len(pdf_files)}개 PDF에서 {total_extracted}개 이미지 추출")
    print(f"저장 위치: {args.output}")


if __name__ == "__main__":
    main()
