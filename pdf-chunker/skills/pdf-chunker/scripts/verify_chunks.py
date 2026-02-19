#!/usr/bin/env python3
"""
Chunks JSON 검증 스크립트

1. 스키마 검증: chunk-schema.md v0.7 필수 필드가 모두 존재하는지 확인
2. 구조 검증: chunk_seq 유일성, section_id 그룹 정합성, split 완전성
3. 파생 필드 일관성: page_start/end ↔ locators.spans 정합성
4. KG 확장 필드 검증: references[].relation, domain_entities[], applicability 타입 확인

참고: 커버리지(원문 누락 여부)는 이 스크립트에서 검증하지 않습니다.
청킹이 Claude Read로 수행되므로, 커버리지는 Stage 2 에이전트가
PDF를 다시 Read로 읽어 직접 확인합니다.
"""

import re
import sys
import argparse
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from collections import Counter, defaultdict


# === 스키마 정의 ===

REQUIRED_CHUNK_FIELDS = [
    "id", "chunk_id", "doc_id", "section_index", "chunk_seq",
    "section_id", "chunk_type", "section_path", "section_title",
    "page_start", "page_end", "locators", "context_prefix", "text",
    "split",
    "prev_chunk_id", "next_chunk_id",
    "images", "tables", "tables_data", "references", "equations",
    "keywords",
]

VALID_CHUNK_TYPES = {"section", "table", "image_caption", "micro", "intro"}

REQUIRED_SPLIT_FIELDS = ["group_id", "split_index", "split_total", "logical_range"]

REQUIRED_LOCATOR_SPAN_FIELDS = ["source_pdf", "pdf_page_start", "pdf_page_end", "doc_page_start", "doc_page_end"]

REQUIRED_REFERENCE_FIELDS = ["target", "type"]

VALID_REFERENCE_TYPES = {"internal", "cross_part", "external"}

VALID_RELATION_TYPES = {"requires", "defines", "restricts", "exempts", "supplements"}

VALID_ENTITY_TYPES = {"ship_type", "structural_member", "equipment", "material", "inspection", "load_condition", "parameter"}


# === 데이터 클래스 ===

@dataclass
class SchemaError:
    """스키마 검증 에러"""
    chunk_seq: int
    chunk_id: str
    field: str
    error: str
    severity: str = "error"  # error, warning


@dataclass
class StructureError:
    """구조 검증 에러"""
    error_type: str  # duplicate_seq, split_gap, split_total_mismatch, ...
    detail: str
    severity: str = "error"


@dataclass
class VerificationReport:
    """통합 검증 리포트"""
    json_file: str

    # 스키마 검증
    total_chunks: int = 0
    schema_errors: List[SchemaError] = field(default_factory=list)

    # 구조 검증
    structure_errors: List[StructureError] = field(default_factory=list)

    @property
    def schema_ok(self) -> bool:
        return not any(e.severity == "error" for e in self.schema_errors)

    @property
    def structure_ok(self) -> bool:
        return not any(e.severity == "error" for e in self.structure_errors)

    @property
    def all_ok(self) -> bool:
        return self.schema_ok and self.structure_ok

    def to_dict(self) -> dict:
        return {
            "json_file": self.json_file,
            "schema": {
                "ok": self.schema_ok,
                "total_chunks": self.total_chunks,
                "error_count": len([e for e in self.schema_errors if e.severity == "error"]),
                "warning_count": len([e for e in self.schema_errors if e.severity == "warning"]),
                "errors": [
                    {"chunk_seq": e.chunk_seq, "chunk_id": e.chunk_id,
                     "field": e.field, "error": e.error, "severity": e.severity}
                    for e in self.schema_errors
                ],
            },
            "structure": {
                "ok": self.structure_ok,
                "error_count": len([e for e in self.structure_errors if e.severity == "error"]),
                "errors": [
                    {"type": e.error_type, "detail": e.detail, "severity": e.severity}
                    for e in self.structure_errors
                ],
            },
        }


# === 검증 클래스 ===

class ChunkVerifier:
    """청크 JSON 검증 클래스 (스키마 + 구조)"""

    def load_chunks(self, json_path: Path) -> Optional[dict]:
        """chunks.json 파일 로드"""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: JSON 파싱 실패: {json_path} — {e}")
            return None
        except FileNotFoundError:
            print(f"Error: 파일을 찾을 수 없습니다: {json_path}")
            return None

    # --- 1. 스키마 검증 ---

    def verify_schema(self, data: dict, report: VerificationReport):
        """모든 청크의 필수 필드 존재 여부 검증"""
        chunks = data.get("chunks", [])
        report.total_chunks = len(chunks)

        for chunk in chunks:
            seq = chunk.get("chunk_seq", -1)
            cid = chunk.get("chunk_id", "?")

            # 필수 필드 존재 확인
            for fld in REQUIRED_CHUNK_FIELDS:
                if fld not in chunk:
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field=fld,
                        error=f"필수 필드 누락"))

            # chunk_type 유효성
            ct = chunk.get("chunk_type")
            if ct is not None and ct not in VALID_CHUNK_TYPES:
                report.schema_errors.append(SchemaError(
                    chunk_seq=seq, chunk_id=cid, field="chunk_type",
                    error=f"유효하지 않은 값: '{ct}' (허용: {VALID_CHUNK_TYPES})"))

            # locators 구조 확인
            locators = chunk.get("locators")
            if locators is not None:
                if not isinstance(locators, dict):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="locators",
                        error="object 타입이어야 함"))
                elif "spans" not in locators:
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="locators.spans",
                        error="spans 배열 누락"))
                else:
                    spans = locators["spans"]
                    if not isinstance(spans, list) or len(spans) == 0:
                        report.schema_errors.append(SchemaError(
                            chunk_seq=seq, chunk_id=cid, field="locators.spans",
                            error="spans는 비어있지 않은 배열이어야 함"))
                    else:
                        for i, span in enumerate(spans):
                            for sf in REQUIRED_LOCATOR_SPAN_FIELDS:
                                if sf not in span:
                                    report.schema_errors.append(SchemaError(
                                        chunk_seq=seq, chunk_id=cid,
                                        field=f"locators.spans[{i}].{sf}",
                                        error="필수 필드 누락"))

            # page_start/end ↔ locators.spans 파생 일관성
            if locators is not None and isinstance(locators, dict):
                spans = locators.get("spans", [])
                if isinstance(spans, list) and len(spans) > 0:
                    try:
                        expected_page_start = min(s["doc_page_start"] for s in spans if "doc_page_start" in s)
                        expected_page_end = max(s["doc_page_end"] for s in spans if "doc_page_end" in s)
                        actual_ps = chunk.get("page_start")
                        actual_pe = chunk.get("page_end")
                        if actual_ps is not None and actual_ps != expected_page_start:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid, field="page_start",
                                error=f"파생 불일치: page_start={actual_ps}, min(spans.doc_page_start)={expected_page_start}",
                                severity="error"))
                        if actual_pe is not None and actual_pe != expected_page_end:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid, field="page_end",
                                error=f"파생 불일치: page_end={actual_pe}, max(spans.doc_page_end)={expected_page_end}",
                                severity="error"))
                    except (ValueError, TypeError):
                        pass  # spans 구조 이상은 위에서 이미 검증

            # split 구조 확인 (null이 아닌 경우)
            split = chunk.get("split")
            if split is not None:
                if not isinstance(split, dict):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="split",
                        error="object 또는 null이어야 함"))
                else:
                    for sf in REQUIRED_SPLIT_FIELDS:
                        if sf not in split:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid, field=f"split.{sf}",
                                error="필수 필드 누락"))
                    # split_index < split_total 확인
                    si = split.get("split_index")
                    st = split.get("split_total")
                    if isinstance(si, int) and isinstance(st, int):
                        if si < 0 or si >= st:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid, field="split.split_index",
                                error=f"범위 초과: split_index={si}, split_total={st}"))

            # references 구조 확인
            refs = chunk.get("references", [])
            if isinstance(refs, list):
                for i, ref in enumerate(refs):
                    for rf in REQUIRED_REFERENCE_FIELDS:
                        if rf not in ref:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"references[{i}].{rf}",
                                error="필수 필드 누락"))
                    rtype = ref.get("type")
                    if rtype and rtype not in VALID_REFERENCE_TYPES:
                        report.schema_errors.append(SchemaError(
                            chunk_seq=seq, chunk_id=cid,
                            field=f"references[{i}].type",
                            error=f"유효하지 않은 값: '{rtype}'"))
                    # relation 유효성 (null 허용 — 후처리 전 기본값)
                    rel = ref.get("relation")
                    if rel is not None and rel not in VALID_RELATION_TYPES:
                        report.schema_errors.append(SchemaError(
                            chunk_seq=seq, chunk_id=cid,
                            field=f"references[{i}].relation",
                            error=f"유효하지 않은 값: '{rel}' (허용: {VALID_RELATION_TYPES})",
                            severity="warning"))
                    # target_norm: null 키 금지
                    tnorm = ref.get("target_norm")
                    if isinstance(tnorm, dict):
                        null_keys = [k for k, v in tnorm.items() if v is None]
                        if null_keys:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"references[{i}].target_norm",
                                error=f"null 키 금지 (해당 키만 포함): {null_keys}",
                                severity="warning"))

            # section_path는 비어있지 않은 배열
            sp = chunk.get("section_path")
            if sp is not None:
                if not isinstance(sp, list) or len(sp) == 0:
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="section_path",
                        error="비어있지 않은 배열이어야 함"))

            # keywords는 배열
            kw = chunk.get("keywords")
            if kw is not None:
                if not isinstance(kw, list):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="keywords",
                        error="배열이어야 함"))
                elif len(kw) == 0:
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="keywords",
                        error="키워드가 비어있음", severity="warning"))

            # text는 비어있지 않은 문자열
            text = chunk.get("text")
            if text is not None:
                if not isinstance(text, str) or len(text.strip()) == 0:
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="text",
                        error="비어있지 않은 문자열이어야 함"))

            # embedding 필드가 남아있으면 경고 (v0.6에서 제거됨)
            if "embedding" in chunk:
                report.schema_errors.append(SchemaError(
                    chunk_seq=seq, chunk_id=cid, field="embedding",
                    error="v0.6에서 제거된 필드. 별도 컬렉션에 저장해야 함", severity="warning"))

            # KG 확장 필드 타입 검증 (존재하는 경우만 — 후처리에서 생성)
            de = chunk.get("domain_entities")
            if de is not None:
                if not isinstance(de, list):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="domain_entities",
                        error="배열 타입이어야 함", severity="warning"))
                else:
                    for i, ent in enumerate(de):
                        for req_f in ["mention", "canonical", "type"]:
                            if req_f not in ent:
                                report.schema_errors.append(SchemaError(
                                    chunk_seq=seq, chunk_id=cid,
                                    field=f"domain_entities[{i}].{req_f}",
                                    error="필수 필드 누락", severity="warning"))
                        etype = ent.get("type")
                        if etype and etype not in VALID_ENTITY_TYPES:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"domain_entities[{i}].type",
                                error=f"유효하지 않은 값: '{etype}'", severity="warning"))

            appl = chunk.get("applicability")
            if appl is not None and not isinstance(appl, dict):
                report.schema_errors.append(SchemaError(
                    chunk_seq=seq, chunk_id=cid, field="applicability",
                    error="object 또는 null이어야 함", severity="warning"))

            nv = chunk.get("normative_values")
            if nv is not None:
                if not isinstance(nv, list):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="normative_values",
                        error="배열 타입이어야 함", severity="warning"))

            # table_oversized (table 타입일 때 확인)
            if ct == "table" and "table_oversized" not in chunk:
                report.schema_errors.append(SchemaError(
                    chunk_seq=seq, chunk_id=cid, field="table_oversized",
                    error="table 타입 청크에 table_oversized 필드 누락", severity="warning"))

            # tables_data 타입 확인 (항상 object, 빈 객체 허용)
            td = chunk.get("tables_data")
            if td is not None:
                if not isinstance(td, dict):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="tables_data",
                        error="object 타입이어야 함 (빈 객체 {} 또는 구조화 데이터)"))
                else:
                    for tname, tdata in td.items():
                        if not isinstance(tdata, dict):
                            continue
                        for req_f in ["title", "columns", "rows"]:
                            if req_f not in tdata:
                                report.schema_errors.append(SchemaError(
                                    chunk_seq=seq, chunk_id=cid,
                                    field=f"tables_data.{tname}.{req_f}",
                                    error="필수 필드 누락"))
            elif "tables_data" in chunk:
                # tables_data가 null이면 경고 (빈 객체 {}를 사용해야 함)
                report.schema_errors.append(SchemaError(
                    chunk_seq=seq, chunk_id=cid, field="tables_data",
                    error="null 대신 빈 객체 {}를 사용해야 함", severity="warning"))

            # equations 타입 확인 (항상 배열, 빈 배열 허용)
            eqs = chunk.get("equations")
            if eqs is not None:
                if not isinstance(eqs, list):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="equations",
                        error="배열 타입이어야 함 (빈 배열 [] 또는 수식 목록)"))
                else:
                    for i, eq in enumerate(eqs):
                        for req_f in ["name", "symbol", "expression"]:
                            if req_f not in eq:
                                report.schema_errors.append(SchemaError(
                                    chunk_seq=seq, chunk_id=cid,
                                    field=f"equations[{i}].{req_f}",
                                    error="필수 필드 누락"))
            elif "equations" in chunk:
                # equations가 null이면 경고 (빈 배열 []을 사용해야 함)
                report.schema_errors.append(SchemaError(
                    chunk_seq=seq, chunk_id=cid, field="equations",
                    error="null 대신 빈 배열 []을 사용해야 함", severity="warning"))

    # --- 2. 구조 검증 ---

    def verify_structure(self, data: dict, report: VerificationReport):
        """청크 간 구조적 정합성 검증"""
        chunks = data.get("chunks", [])
        if not chunks:
            return

        # chunk_seq 유일성
        seq_counts = Counter(c.get("chunk_seq") for c in chunks)
        for seq, count in seq_counts.items():
            if count > 1:
                report.structure_errors.append(StructureError(
                    error_type="duplicate_seq",
                    detail=f"chunk_seq={seq}가 {count}번 중복됨"))

        # chunk_seq 연속성 (0부터 시작, 빈틈 없어야 함)
        seqs = sorted(c.get("chunk_seq", -1) for c in chunks)
        if seqs[0] != 0:
            report.structure_errors.append(StructureError(
                error_type="seq_not_zero",
                detail=f"chunk_seq가 0이 아닌 {seqs[0]}부터 시작"))
        expected = list(range(seqs[0], seqs[0] + len(seqs)))
        if seqs != expected:
            missing = set(expected) - set(seqs)
            if missing:
                report.structure_errors.append(StructureError(
                    error_type="seq_gap",
                    detail=f"chunk_seq 빈틈: {sorted(missing)}"))

        # group_id 기반 split 그룹 검증
        split_groups: Dict[str, List[dict]] = defaultdict(list)
        for c in chunks:
            if c.get("split") is not None:
                gid = c["split"].get("group_id", c.get("section_id", "?"))
                split_groups[gid].append(c)

        for gid, group in split_groups.items():
            totals = set(c["split"]["split_total"] for c in group if "split_total" in c.get("split", {}))
            if len(totals) > 1:
                report.structure_errors.append(StructureError(
                    error_type="split_total_mismatch",
                    detail=f"group_id='{gid}': split_total 불일치 {totals}"))

            if len(totals) == 1:
                expected_total = totals.pop()
                if len(group) != expected_total:
                    report.structure_errors.append(StructureError(
                        error_type="split_count_mismatch",
                        detail=f"group_id='{gid}': split_total={expected_total}이지만 실제 {len(group)}개"))

                indices = sorted(c["split"]["split_index"] for c in group if "split_index" in c.get("split", {}))
                expected_indices = list(range(expected_total))
                if indices != expected_indices:
                    report.structure_errors.append(StructureError(
                        error_type="split_index_gap",
                        detail=f"group_id='{gid}': split_index 빈틈 (기대: {expected_indices}, 실제: {indices})"))

        # section_index: 같은 section_id의 청크들은 동일 section_index를 공유
        sid_to_si: Dict[str, set] = defaultdict(set)
        for c in chunks:
            sid = c.get("section_id")
            si = c.get("section_index")
            if sid and si is not None:
                sid_to_si[sid].add(si)

        for sid, si_set in sid_to_si.items():
            if len(si_set) > 1:
                report.structure_errors.append(StructureError(
                    error_type="section_index_mismatch",
                    detail=f"section_id='{sid}': section_index가 일관되지 않음 {si_set}"))

        # prev/next_chunk_id 정합성
        sorted_chunks = sorted(chunks, key=lambda c: c.get("chunk_seq", 0))
        chunk_ids = {c.get("chunk_id") for c in sorted_chunks}
        for i, c in enumerate(sorted_chunks):
            cid = c.get("chunk_id", "?")
            prev_id = c.get("prev_chunk_id")
            next_id = c.get("next_chunk_id")

            # 첫 청크는 prev가 null이어야
            if i == 0 and prev_id is not None:
                report.structure_errors.append(StructureError(
                    error_type="prev_chunk_id_error",
                    detail=f"첫 청크({cid})의 prev_chunk_id가 null이 아님: '{prev_id}'",
                    severity="warning"))
            # 마지막 청크는 next가 null이어야
            if i == len(sorted_chunks) - 1 and next_id is not None:
                report.structure_errors.append(StructureError(
                    error_type="next_chunk_id_error",
                    detail=f"마지막 청크({cid})의 next_chunk_id가 null이 아님: '{next_id}'",
                    severity="warning"))
            # 존재하는 chunk_id를 가리키는지
            if prev_id is not None and prev_id not in chunk_ids:
                report.structure_errors.append(StructureError(
                    error_type="prev_chunk_id_dangling",
                    detail=f"{cid}의 prev_chunk_id '{prev_id}'가 존재하지 않음"))
            if next_id is not None and next_id not in chunk_ids:
                report.structure_errors.append(StructureError(
                    error_type="next_chunk_id_dangling",
                    detail=f"{cid}의 next_chunk_id '{next_id}'가 존재하지 않음"))

    # --- 통합 검증 ---

    def verify(self, json_path: Path) -> Optional[VerificationReport]:
        """chunks.json 스키마 + 구조 검증"""
        report = VerificationReport(
            json_file=str(json_path.name),
        )

        # JSON 로드
        data = self.load_chunks(json_path)
        if data is None:
            return None

        # 1. 스키마 검증
        self.verify_schema(data, report)

        # 2. 구조 검증
        self.verify_structure(data, report)

        return report

    def print_report(self, report: VerificationReport, verbose: bool = False):
        """검증 리포트 출력"""
        print(f"\n{'='*60}")
        print(f"검증 결과: {report.json_file}")
        print(f"{'='*60}")

        # 스키마
        schema_status = "OK" if report.schema_ok else "FAIL"
        err_count = len([e for e in report.schema_errors if e.severity == "error"])
        warn_count = len([e for e in report.schema_errors if e.severity == "warning"])
        print(f"[스키마] {schema_status} — 청크 {report.total_chunks}개, 에러 {err_count}, 경고 {warn_count}")

        if verbose and report.schema_errors:
            for e in report.schema_errors:
                icon = "!!" if e.severity == "error" else "W "
                print(f"  {icon} seq={e.chunk_seq} ({e.chunk_id}): {e.field} — {e.error}")

        # 구조
        struct_status = "OK" if report.structure_ok else "FAIL"
        struct_err = len([e for e in report.structure_errors if e.severity == "error"])
        print(f"[구조]   {struct_status} — 에러 {struct_err}")

        if verbose and report.structure_errors:
            for e in report.structure_errors:
                icon = "!!" if e.severity == "error" else "W "
                print(f"  {icon} {e.error_type}: {e.detail}")

        # 종합
        overall = "PASS" if report.all_ok else "FAIL"
        print(f"\n종합: {overall}")


def main():
    parser = argparse.ArgumentParser(
        description='chunks.json 스키마/구조 검증 (커버리지는 Stage 2 에이전트가 수행)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # chunks.json 검증
  python verify_chunks.py output.chunks.json -v

  # JSON으로 결과 저장
  python verify_chunks.py output.chunks.json --export report.json
        """
    )

    parser.add_argument('json_path', help='검증할 chunks.json 파일 경로')
    parser.add_argument('-v', '--verbose', action='store_true', help='상세 출력')
    parser.add_argument('--export', metavar='FILE', help='검증 결과를 JSON 파일로 저장')

    args = parser.parse_args()

    verifier = ChunkVerifier()
    json_path = Path(args.json_path)

    report = verifier.verify(json_path)
    if report is None:
        sys.exit(1)
    verifier.print_report(report, verbose=args.verbose)

    if args.export:
        with open(args.export, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\n검증 결과 저장: {args.export}")

    # 종료 코드
    if not report.all_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
