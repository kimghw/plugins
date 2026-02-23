#!/usr/bin/env python3
"""
Chunks JSON 검증 스크립트

1. 스키마 검증: chunk-schema.md v0.7 필수 필드가 모두 존재하는지 확인
2. 구조 검증: chunk_seq 유일성, section_id 그룹 정합성, split 완전성
3. 파생 필드 일관성: page_start/end ↔ locators.spans 정합성
4. KG 확장 필드 검증: references[].relation, domain_entities[], applicability 타입 확인
5. 커버리지 검증: PDF 원문 문장의 마지막 5단어가 chunks.text에 존재하는지 확인
   - 문장 분리 → 각 문장에서 순수 단어만 추출 → 마지막 5단어 → chunks text에 매칭
   - 5단어 미만 문장은 skip, 동일 5단어 중복은 1회만 체크
   - 90%+ 목표
6. 수치/단위 검증: PDF 원문의 수치+단위 패턴(예: ≥ 0.5 mm)이 chunks에 정확히 보존되었는지 확인
   - 앞뒤 컨텍스트 단어(각 2개)와 함께 search_key를 구성하여 위치 특정
   - 동일 search_key 중복은 1회만 체크
   - 90%+ 목표
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
class CoverageResult:
    """커버리지 검증 결과"""
    total_sentences: int = 0
    matched_sentences: int = 0
    skipped_sentences: int = 0  # 5단어 미만 또는 중복으로 skip된 문장
    unmatched: List[Dict[str, Any]] = field(default_factory=list)  # 매칭 안 된 문장 정보

    @property
    def coverage_pct(self) -> float:
        checked = self.total_sentences - self.skipped_sentences
        if checked == 0:
            return 100.0
        return (self.matched_sentences / checked) * 100


@dataclass
class NumericResult:
    """수치/단위 검증 결과"""
    total_patterns: int = 0
    matched_patterns: int = 0
    skipped_patterns: int = 0
    unmatched: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def numeric_pct(self) -> float:
        checked = self.total_patterns - self.skipped_patterns
        if checked == 0:
            return 100.0
        return (self.matched_patterns / checked) * 100


@dataclass
class VerificationReport:
    """통합 검증 리포트"""
    json_file: str

    # 스키마 검증
    total_chunks: int = 0
    schema_errors: List[SchemaError] = field(default_factory=list)

    # 구조 검증
    structure_errors: List[StructureError] = field(default_factory=list)

    # 커버리지 검증
    coverage: Optional[CoverageResult] = None

    # 수치/단위 검증
    numeric: Optional[NumericResult] = None

    @property
    def schema_ok(self) -> bool:
        return not any(e.severity == "error" for e in self.schema_errors)

    @property
    def structure_ok(self) -> bool:
        return not any(e.severity == "error" for e in self.structure_errors)

    @property
    def coverage_ok(self) -> bool:
        if self.coverage is None:
            return True  # 커버리지 미실행이면 통과
        return self.coverage.coverage_pct >= 90.0

    @property
    def numeric_ok(self) -> bool:
        if self.numeric is None:
            return True  # 수치 검증 미실행이면 통과
        return self.numeric.numeric_pct >= 90.0

    @property
    def all_ok(self) -> bool:
        return self.schema_ok and self.structure_ok and self.coverage_ok and self.numeric_ok

    def to_dict(self) -> dict:
        d = {
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
        if self.coverage is not None:
            d["coverage"] = {
                "ok": self.coverage_ok,
                "total_sentences": self.coverage.total_sentences,
                "matched": self.coverage.matched_sentences,
                "skipped": self.coverage.skipped_sentences,
                "coverage_pct": round(self.coverage.coverage_pct, 1),
                "unmatched_count": len(self.coverage.unmatched),
                "unmatched": self.coverage.unmatched[:20],  # 상위 20개만
            }
        if self.numeric is not None:
            checked = self.numeric.total_patterns - self.numeric.skipped_patterns
            d["numeric"] = {
                "ok": self.numeric_ok,
                "total_patterns": self.numeric.total_patterns,
                "matched": self.numeric.matched_patterns,
                "skipped": self.numeric.skipped_patterns,
                "numeric_pct": round(self.numeric.numeric_pct, 1),
                "unmatched_count": len(self.numeric.unmatched),
                "unmatched": self.numeric.unmatched[:20],
            }
        return d


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
                            if not isinstance(span, dict):
                                report.schema_errors.append(SchemaError(
                                    chunk_seq=seq, chunk_id=cid,
                                    field=f"locators.spans[{i}]",
                                    error=f"객체여야 하지만 {type(span).__name__} 타입임"))
                                continue
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
                    if not isinstance(ref, dict):
                        report.schema_errors.append(SchemaError(
                            chunk_seq=seq, chunk_id=cid,
                            field=f"references[{i}]",
                            error=f"객체여야 하지만 {type(ref).__name__} 타입임"))
                        continue
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

            # ontology_keywords 검증
            ok = chunk.get("ontology_keywords")
            if ok is not None:
                if not isinstance(ok, list):
                    report.schema_errors.append(SchemaError(
                        chunk_seq=seq, chunk_id=cid, field="ontology_keywords",
                        error="배열이어야 함", severity="warning"))
                else:
                    valid_types = {"ship_type", "structural_member", "equipment",
                                   "material", "inspection", "load_condition", "parameter"}
                    for j, item in enumerate(ok):
                        if not isinstance(item, dict):
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"ontology_keywords[{j}]",
                                error="객체여야 함", severity="warning"))
                            continue
                        if "mention" not in item or "type" not in item:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"ontology_keywords[{j}]",
                                error="mention과 type 필드 필요", severity="warning"))
                        elif item.get("type") not in valid_types:
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"ontology_keywords[{j}]",
                                error=f"유효하지 않은 type: {item.get('type')} (허용: {', '.join(sorted(valid_types))})",
                                severity="warning"))

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
                        if not isinstance(ent, dict):
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"domain_entities[{i}]",
                                error=f"객체여야 하지만 {type(ent).__name__} 타입임", severity="warning"))
                            continue
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
                        if not isinstance(eq, dict):
                            report.schema_errors.append(SchemaError(
                                chunk_seq=seq, chunk_id=cid,
                                field=f"equations[{i}]",
                                error=f"객체여야 하지만 {type(eq).__name__} 타입임"))
                            continue
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

    # --- 3. 커버리지 검증 ---

    @staticmethod
    def _extract_words(text: str) -> List[str]:
        """텍스트에서 순수 단어만 추출 (특수문자 제거)"""
        tokens = re.findall(r'[가-힣a-zA-Z0-9]+', text)
        return tokens

    # 수치 패턴 정규식: (선택)연산자 + 숫자(소수점 포함) + (선택)단위
    _NUMERIC_RE = re.compile(
        r'(?P<operator>[≥≤><±~약])?'
        r'\s*'
        r'(?P<value>\d+(?:\.\d+)?)'
        r'\s*'
        r'(?P<unit>[a-zA-Z℃%°㎜㎝㎡㎥㎏㎐]+)?'
    )

    @staticmethod
    def _extract_numeric_patterns(text: str) -> List[Dict[str, Any]]:
        """텍스트에서 수치+단위 패턴을 앞뒤 컨텍스트 단어와 함께 추출

        Returns: [
            {
                "raw": "≥ 0.5 mm",
                "operator": "≥",
                "value": "0.5",
                "unit": "mm",
                "context_before": ["상태를"],
                "context_after": ["사이에"],
                "search_key": "상태를0.5mm사이에"
            }, ...
        ]
        """
        results = []
        for m in ChunkVerifier._NUMERIC_RE.finditer(text):
            operator = m.group("operator") or ""
            value = m.group("value")
            unit = m.group("unit") or ""

            # 단위도 연산자도 없는 순수 숫자는 skip (조항 번호, 연도 등)
            if not operator and not unit:
                continue

            raw = m.group(0).strip()

            # 앞뒤 컨텍스트 단어 추출 (각 최대 2개, 소수점 포함)
            before_text = text[:m.start()]
            after_text = text[m.end():]
            words_before = re.findall(r'[가-힣a-zA-Z0-9.]+', before_text)
            words_after = re.findall(r'[가-힣a-zA-Z0-9.]+', after_text)
            ctx_before = words_before[-2:] if len(words_before) >= 2 else words_before
            ctx_after = words_after[:2] if len(words_after) >= 2 else words_after

            # search_key: 앞 컨텍스트 + 값 + 영문단위 + 뒤 컨텍스트 (이어 붙임)
            # 특수 단위 기호(%,℃,°,㎜ 등)는 _extract_words 토큰에 포함되지 않으므로 제외
            alpha_unit = re.sub(r'[^a-zA-Z]', '', unit)
            search_key = "".join(ctx_before) + value + alpha_unit + "".join(ctx_after)

            results.append({
                "raw": raw,
                "operator": operator or None,
                "value": value,
                "unit": unit or None,
                "context_before": ctx_before,
                "context_after": ctx_after,
                "search_key": search_key,
            })
        return results

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """정규식 기반 문장 분리 (기술 문서용)

        마침표/물음표/느낌표 뒤 공백 또는 줄바꿈으로 분리.
        괄호 안 마침표, 소수점, 조항 번호(101. 등)는 분리하지 않음.
        """
        # 줄바꿈을 기준으로 먼저 분리, 그 안에서 문장 종결 부호로 재분리
        lines = text.split('\n')
        sentences = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 문장 종결: 한글/숫자/닫는괄호 뒤 마침표 + (공백 또는 끝)
            parts = re.split(r'(?<=[가-힣a-zA-Z0-9\)）\]])\.(?:\s|$)', line)
            for part in parts:
                part = part.strip()
                if part:
                    sentences.append(part)
        return sentences

    def _extract_pdf_text(self, pdf_path: Path, data: dict) -> Optional[str]:
        """PDF에서 chunks가 참조하는 페이지의 텍스트를 추출"""
        try:
            import fitz
        except ImportError:
            print("Warning: pymupdf 미설치 — PDF 검증 건너뜀")
            return None

        # chunks에서 PDF 페이지 범위 추출
        chunks = data.get("chunks", [])
        pdf_pages = set()
        for c in chunks:
            locators = c.get("locators", {})
            for span in locators.get("spans", []):
                ps = span.get("pdf_page_start")
                pe = span.get("pdf_page_end")
                if ps is not None and pe is not None:
                    for p in range(ps, pe + 1):
                        pdf_pages.add(p)

        try:
            doc = fitz.open(str(pdf_path))
        except Exception as e:
            print(f"Warning: PDF 열기 실패 — {e}")
            return None

        pdf_text = ""
        if pdf_pages:
            for page_num in sorted(pdf_pages):
                idx = page_num - 1  # fitz는 0-indexed
                if 0 <= idx < len(doc):
                    pdf_text += doc[idx].get_text() + "\n"
        else:
            for page in doc:
                pdf_text += page.get_text() + "\n"
        doc.close()

        if not pdf_text.strip():
            print("Warning: PDF에서 텍스트를 추출할 수 없음")
            return None

        return pdf_text

    def verify_coverage(self, pdf_text: str, data: dict, report: VerificationReport):
        """PDF 원문 문장의 마지막 5단어가 chunks.text에 존재하는지 검증

        - 동일 5단어 중복은 한 번만 체크 (페이지 헤더 등 반복 제거)
        """
        result = CoverageResult()
        chunks = data.get("chunks", [])

        # 1. 문장 분리
        sentences = self._split_sentences(pdf_text)
        result.total_sentences = len(sentences)

        # 2. chunks의 전체 text + section_path를 합침 (공백 제거하여 연속 문자열로)
        all_text_parts = []
        for c in chunks:
            all_text_parts.append(c.get("text", ""))
            for sp in c.get("section_path", []):
                all_text_parts.append(sp)
        all_chunks_text_raw = " ".join(all_text_parts)
        all_chunks_words = self._extract_words(all_chunks_text_raw)
        all_chunks_joined = "".join(all_chunks_words)

        # 3. 각 문장에서 마지막 5단어 추출 → 중복 제거 후 검색
        seen_keys = set()
        for sent in sentences:
            words = self._extract_words(sent)
            if len(words) < 5:
                result.skipped_sentences += 1
                continue

            last5_words = words[-5:]
            last5_joined = "".join(last5_words)
            last5_display = " ".join(last5_words)

            if last5_joined in seen_keys:
                result.skipped_sentences += 1
                continue
            seen_keys.add(last5_joined)

            if last5_joined in all_chunks_joined:
                result.matched_sentences += 1
            else:
                result.unmatched.append({
                    "sentence": sent.strip()[:100],
                    "last5": last5_display,
                })

        report.coverage = result

    # --- 4. 수치/단위 검증 ---

    def verify_numerics(self, pdf_text: str, data: dict, report: VerificationReport):
        """PDF 원문의 수치+단위 패턴이 chunks에 정확히 보존되었는지 검증

        - 각 수치 패턴의 앞뒤 컨텍스트 단어를 포함한 search_key로 위치 특정
        - 동일 search_key 중복은 1회만 체크
        """
        result = NumericResult()
        chunks = data.get("chunks", [])

        # 1. PDF에서 수치 패턴 추출
        pdf_patterns = self._extract_numeric_patterns(pdf_text)
        result.total_patterns = len(pdf_patterns)

        if not pdf_patterns:
            report.numeric = result
            return

        # 2. 청크 전체 텍스트 결합 (원문 그대로 — 수치/단위/특수기호 보존)
        all_text_parts = []
        for c in chunks:
            all_text_parts.append(c.get("text", ""))
            for sp in c.get("section_path", []):
                all_text_parts.append(sp)
        all_chunks_raw = " ".join(all_text_parts)

        # 3. 청크 텍스트에서도 수치 패턴의 검색 대상 구성
        #    단어 + 숫자 + 소수점을 모두 이어 붙인 문자열 (search_key와 동일 토큰 규칙 적용)
        chunks_words = re.findall(r'[가-힣a-zA-Z0-9.]+', all_chunks_raw)
        chunks_joined = "".join(chunks_words)

        # 4. 각 PDF 수치 패턴의 search_key가 청크에 존재하는지 확인
        seen_keys = set()
        for pat in pdf_patterns:
            key = pat["search_key"]

            if key in seen_keys:
                result.skipped_patterns += 1
                continue
            seen_keys.add(key)

            if key in chunks_joined:
                result.matched_patterns += 1
            else:
                ctx_before_str = " ".join(pat["context_before"])
                ctx_after_str = " ".join(pat["context_after"])
                result.unmatched.append({
                    "raw": pat["raw"],
                    "value": pat["value"],
                    "unit": pat["unit"],
                    "operator": pat["operator"],
                    "context_before": ctx_before_str,
                    "context_after": ctx_after_str,
                    "search_key": key,
                })

        report.numeric = result

    # --- 통합 검증 ---

    def verify(self, json_path: Path, pdf_path: Path = None) -> Optional[VerificationReport]:
        """chunks.json 스키마 + 구조 + 커버리지 검증"""
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

        # 3. PDF 기반 검증 (커버리지 + 수치/단위)
        if pdf_path is not None:
            pdf_text = self._extract_pdf_text(pdf_path, data)
            if pdf_text:
                self.verify_coverage(pdf_text, data, report)
                self.verify_numerics(pdf_text, data, report)

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

        # 커버리지
        if report.coverage is not None:
            cov = report.coverage
            cov_status = "OK" if report.coverage_ok else "FAIL"
            checked = cov.total_sentences - cov.skipped_sentences
            print(f"[커버리지] {cov_status} — {cov.coverage_pct:.1f}% "
                  f"(매칭 {cov.matched_sentences}/{checked}, "
                  f"skip {cov.skipped_sentences}, 총 문장 {cov.total_sentences})")

            if verbose and cov.unmatched:
                shown = cov.unmatched[:20]
                for u in shown:
                    print(f"  !! 미매칭: \"{u['last5']}\" ← {u['sentence']}")
                if len(cov.unmatched) > 20:
                    print(f"  ... 외 {len(cov.unmatched) - 20}건")

        # 수치/단위
        if report.numeric is not None:
            num = report.numeric
            num_status = "OK" if report.numeric_ok else "FAIL"
            checked = num.total_patterns - num.skipped_patterns
            print(f"[수치]   {num_status} — {num.numeric_pct:.1f}% "
                  f"(매칭 {num.matched_patterns}/{checked}, "
                  f"skip {num.skipped_patterns}, 총 패턴 {num.total_patterns})")

            if verbose and num.unmatched:
                shown = num.unmatched[:20]
                for u in shown:
                    ctx_str = f"(앞: {u['context_before']} / 뒤: {u['context_after']})"
                    print(f"  !! 미매칭: \"{u['raw']}\" {ctx_str}")
                if len(num.unmatched) > 20:
                    print(f"  ... 외 {len(num.unmatched) - 20}건")

        # 종합
        overall = "PASS" if report.all_ok else "FAIL"
        print(f"\n종합: {overall}")


def main():
    parser = argparse.ArgumentParser(
        description='chunks.json 스키마/구조/커버리지 검증',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 스키마+구조만 검증 (PDF 없이)
  python verify_chunks.py output.chunks.json -v

  # 스키마+구조+커버리지 검증 (PDF 필요)
  python verify_chunks.py output.chunks.json --pdf input.pdf -v

  # JSON으로 결과 저장
  python verify_chunks.py output.chunks.json --pdf input.pdf --export report.json
        """
    )

    parser.add_argument('json_path', help='검증할 chunks.json 파일 경로')
    parser.add_argument('--pdf', metavar='FILE', help='커버리지 검증용 원본 PDF 경로')
    parser.add_argument('-v', '--verbose', action='store_true', help='상세 출력')
    parser.add_argument('--export', metavar='FILE', help='검증 결과를 JSON 파일로 저장')
    parser.add_argument('--unmatched-log', metavar='FILE', help='미매칭 목록을 별도 로그 파일로 저장')

    args = parser.parse_args()

    verifier = ChunkVerifier()
    json_path = Path(args.json_path)
    pdf_path = Path(args.pdf) if args.pdf else None

    report = verifier.verify(json_path, pdf_path=pdf_path)
    if report is None:
        sys.exit(1)
    verifier.print_report(report, verbose=args.verbose)

    if args.export:
        with open(args.export, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\n검증 결과 저장: {args.export}")

    # 미매칭 로그: --unmatched-log 지정 시 해당 경로, 아니면 output/unmatched_logs/에 자동 생성
    has_cov_unmatched = report.coverage and report.coverage.unmatched
    has_num_unmatched = report.numeric and report.numeric.unmatched
    if has_cov_unmatched or has_num_unmatched:
        if args.unmatched_log:
            log_path = Path(args.unmatched_log)
        else:
            log_dir = json_path.parent / "unmatched_logs"
            log_dir.mkdir(exist_ok=True)
            log_path = log_dir / json_path.with_suffix('.unmatched.log').name
        with open(log_path, 'w', encoding='utf-8') as f:
            if has_cov_unmatched:
                cov = report.coverage
                checked = cov.total_sentences - cov.skipped_sentences
                f.write(f"[커버리지] {cov.coverage_pct:.1f}% "
                        f"(매칭 {cov.matched_sentences}/{checked}, "
                        f"미매칭 {len(cov.unmatched)}건)\n")
                f.write(f"{'='*60}\n")
                for u in cov.unmatched:
                    f.write(f"[{u['last5']}] ← {u['sentence']}\n")
            if has_num_unmatched:
                num = report.numeric
                checked = num.total_patterns - num.skipped_patterns
                f.write(f"\n[수치] {num.numeric_pct:.1f}% "
                        f"(매칭 {num.matched_patterns}/{checked}, "
                        f"미매칭 {len(num.unmatched)}건)\n")
                f.write(f"{'='*60}\n")
                for u in num.unmatched:
                    f.write(f"[{u['raw']}] (앞: {u['context_before']} / 뒤: {u['context_after']})\n")
        print(f"미매칭 로그 저장: {log_path}")

    # 종료 코드
    if not report.all_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
