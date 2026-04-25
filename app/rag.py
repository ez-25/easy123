import csv
import os
import re
from pathlib import Path
from typing import Any

from app.config import settings

NORMALIZED_COLUMNS = [
    "category",
    "welfareType",
    "servId",
    "servNm",
    "region",
    "agency",
    "department",
    "intrsThemaArray",
    "lifeArray",
    "srvPvsnNm",
    "sprtCycNm",
    "servDgst",
    "servDtlLink",
    "inqNum",
    "contact",
    "sourceDataset",
]
FIELD_WEIGHTS: dict[str, float] = {
    "servNm": 2.8,
    "lifeArray": 1.9,
    "servDgst": 2.4,
    "srvPvsnNm": 1.0,
    "intrsThemaArray": 0.8,
    "category": 0.5,
    "region": 1.1,
}
KOREAN_STOPWORDS = {
    "학생",
    "학생의",
    "학생이",
    "지원",
    "지원이",
    "연계",
    "필요",
    "요청",
    "학교",
    "기관",
    "제도",
    "대한",
    "및",
    "또는",
    "에서",
    "으로",
    "있는",
    "위한",
    "통합",
    "신청",
    "신청서",
    "정보",
}
DOMAIN_KEYWORDS: dict[str, set[str]] = {
    "academic": {
        "학업",
        "학습",
        "기초학력",
        "기초",
        "수학",
        "국어",
        "학습부진",
        "숙제",
        "집중",
        "수업",
        "무기력",
        "교육비",
        "학비",
        "멘토링",
    },
    "counseling": {
        "정서",
        "심리",
        "상담",
        "불안",
        "우울",
        "위축",
        "분노",
        "스트레스",
        "wee",
        "위클래스",
        "정신건강",
        "치유",
    },
    "social": {
        "또래",
        "갈등",
        "사회성",
        "충동",
        "관계",
        "폭력",
        "친구",
        "집단",
        "대인관계",
    },
    "care": {
        "돌봄",
        "방과후",
        "방과 후",
        "아이돌봄",
        "보호",
        "귀가",
        "맞벌이",
        "조손",
        "지역아동센터",
        "청소년방과후아카데미",
    },
    "economic": {
        "기초생활수급자",
        "수급자",
        "차상위",
        "저소득",
        "교육비",
        "생계",
        "급여",
        "장학금",
        "생활비",
        "한부모",
    },
    "risk": {
        "학대",
        "자해",
        "가정폭력",
        "성폭력",
        "가출",
        "긴급",
        "위기",
        "보호시설",
    },
}
SECONDARY_ONLY_KEYWORDS = {
    "고등학생",
    "고등학교",
    "고1",
    "고2",
    "고3",
    "중학생",
    "중학교",
    "대학생",
}
ELEMENTARY_HINT_KEYWORDS = {"초등", "초중", "아동", "청소년", "학생"}
NATIONWIDE_KEYWORDS = {"전국", "전국단위", "전국공통", "중앙부처", "중앙", "전국 공통"}
LOW_INCOME_KEYWORDS = {
    "기초생활수급자",
    "수급자",
    "차상위",
    "한부모",
    "저소득",
    "복지급여",
    "중위소득",
}
LOCAL_CENTER_KEYWORDS = {
    "센터",
    "수련관",
    "복지관",
    "상담복지센터",
    "정신건강복지센터",
    "가족센터",
    "학교밖청소년지원센터",
    "청소년상담복지센터",
}
REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "서울": ("서울", "서울특별시", "서울시"),
    "부산": ("부산", "부산광역시", "부산시"),
    "대구": ("대구", "대구광역시", "대구시"),
    "인천": ("인천", "인천광역시", "인천시"),
    "광주": ("광주", "광주광역시", "광주시"),
    "대전": ("대전", "대전광역시", "대전시"),
    "울산": ("울산", "울산광역시", "울산시"),
    "세종": ("세종", "세종특별자치시"),
    "경기": ("경기", "경기도"),
    "강원": ("강원", "강원도", "강원특별자치도"),
    "충북": ("충북", "충청북도"),
    "충남": ("충남", "충청남도"),
    "전북": ("전북", "전라북도", "전북특별자치도"),
    "전남": ("전남", "전라남도"),
    "경북": ("경북", "경상북도"),
    "경남": ("경남", "경상남도"),
    "제주": ("제주", "제주도", "제주특별자치도"),
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_path(path_str: str | Path) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return _project_root() / path


def _parse_csv_list(value: str | None) -> list[Path]:
    raw = (value or "").strip()
    if not raw:
        return []
    paths: list[Path] = []
    for item in raw.split(","):
        cleaned = item.strip()
        if cleaned:
            paths.append(_resolve_path(cleaned))
    return paths


def _safe_int(value: str) -> int:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_region_name(region: str) -> str:
    cleaned = _normalize_text(region)
    if not cleaned:
        return ""
    for canonical, aliases in REGION_ALIASES.items():
        if any(alias in cleaned for alias in aliases):
            return canonical
    return cleaned


def _extract_region_tokens(region: str) -> list[str]:
    cleaned = _normalize_text(region)
    if not cleaned:
        return []
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", cleaned)
    unique: list[str] = []
    canonical = _normalize_region_name(cleaned)
    if canonical:
        unique.append(canonical)
    for token in tokens:
        if token not in unique:
            unique.append(token)
    return unique


def _has_explicit_local_requirement(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return bool(re.search(r"[가-힣]+(특별시|광역시|특별자치시|특별자치도|도|시|군|구)", normalized))


def _build_searchable_text(metadata: dict[str, str]) -> str:
    return " ".join(_normalize_text(metadata.get(column, "")) for column in NORMALIZED_COLUMNS).lower()


def _normalize_row(row: dict[str, str], source_dataset: str) -> dict[str, str]:
    region = _normalize_text(row.get("region", "") or row.get("agency", "") or row.get("department", ""))
    metadata = {
        "category": _normalize_text(row.get("category", "")),
        "welfareType": _normalize_text(row.get("welfareType", "")),
        "servId": _normalize_text(row.get("servId", "")),
        "servNm": _normalize_text(row.get("servNm", "")),
        "region": region,
        "agency": _normalize_text(row.get("agency", "")),
        "department": _normalize_text(row.get("department", "")),
        "intrsThemaArray": _normalize_text(row.get("intrsThemaArray", "")),
        "lifeArray": _normalize_text(row.get("lifeArray", "")),
        "srvPvsnNm": _normalize_text(row.get("srvPvsnNm", "")),
        "sprtCycNm": _normalize_text(row.get("sprtCycNm", "")),
        "servDgst": _normalize_text(row.get("servDgst", "")),
        "servDtlLink": _normalize_text(row.get("servDtlLink", "")),
        "inqNum": str(_safe_int(row.get("inqNum", ""))),
        "contact": _normalize_text(row.get("contact", "")),
        "sourceDataset": source_dataset,
    }
    metadata["_search_text"] = _build_searchable_text(metadata)
    return metadata


def _load_documents(csv_paths: list[Path]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for csv_path in csv_paths:
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            required_columns = {"category", "welfareType", "servId", "servNm", "agency", "servDgst"}
            fieldnames = set(reader.fieldnames or [])
            missing_columns = required_columns - fieldnames
            if missing_columns:
                raise ValueError(f"{csv_path.name} is missing required columns: {sorted(missing_columns)}")

            for row in reader:
                metadata = _normalize_row(row, source_dataset=csv_path.name)
                dedupe_key = (
                    metadata["servId"],
                    metadata["servNm"],
                    metadata["sourceDataset"],
                )
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                documents.append({"metadata": metadata, "page_content": metadata["_search_text"]})

    if not documents:
        raise ValueError("No records found in configured CSV files.")
    return documents


def _tokenize_query(query: str) -> list[str]:
    raw_terms = re.findall(r"[가-힣A-Za-z0-9]{2,}", query.lower())
    deduped: list[str] = []
    for term in raw_terms:
        if term in KOREAN_STOPWORDS:
            continue
        if term not in deduped:
            deduped.append(term)
    return deduped


def _contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _score_text_match(query_terms: list[str], text: str) -> float:
    if not query_terms:
        return 0.0
    matches = sum(1 for term in query_terms if term in text)
    return matches / len(query_terms)


def _weighted_row_match_score(query_terms: list[str], metadata: dict[str, str]) -> float:
    if not query_terms:
        return 0.0

    weighted_score = 0.0
    total_weight = 0.0

    for field, weight in FIELD_WEIGHTS.items():
        field_text = metadata.get(field, "").lower()
        total_weight += weight
        if not field_text:
            continue
        hits = sum(1 for term in query_terms if term in field_text)
        weighted_score += (hits / len(query_terms)) * weight

    return weighted_score / total_weight if total_weight else 0.0


def _domain_profile_scores(text: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in text)
        scores[domain] = min(1.0, hits / 3)
    return scores


def _score_region_alignment(metadata: dict[str, str], student_region: str) -> float:
    if not student_region:
        return 0.0

    doc_region_text = " ".join(
        [
            metadata.get("region", ""),
            metadata.get("agency", ""),
            metadata.get("department", ""),
            metadata.get("servDgst", ""),
            metadata.get("lifeArray", ""),
        ]
    )
    doc_region_text = _normalize_text(doc_region_text)
    if not doc_region_text:
        return 0.0

    student_region_tokens = _extract_region_tokens(student_region)
    if not student_region_tokens:
        return 0.0

    canonical_student_region = _normalize_region_name(student_region)
    canonical_doc_region = _normalize_region_name(doc_region_text)

    exact_hits = sum(1 for token in student_region_tokens if token and token in doc_region_text)
    if canonical_student_region and canonical_student_region == canonical_doc_region:
        if exact_hits >= 2:
            return 0.24
        return 0.18

    if canonical_student_region and canonical_student_region in doc_region_text:
        return 0.12

    if exact_hits >= 2:
        return 0.16
    if exact_hits == 1:
        return 0.08

    if _has_explicit_local_requirement(doc_region_text):
        if _contains_any(metadata.get("servNm", ""), LOCAL_CENTER_KEYWORDS):
            return -0.45
        if "장학금" in metadata.get("srvPvsnNm", ""):
            return -0.55
        return -0.35

    if _contains_any(doc_region_text, NATIONWIDE_KEYWORDS):
        return 0.06

    if canonical_student_region and canonical_doc_region and canonical_student_region != canonical_doc_region:
        if _contains_any(metadata.get("servNm", ""), LOCAL_CENTER_KEYWORDS):
            return -0.18
        if "장학금/지역연고" in metadata.get("srvPvsnNm", ""):
            return -0.22
        return -0.08

    return 0.0


def _score_context_alignment(
    metadata: dict[str, str],
    context: dict[str, Any] | None,
    domain_scores: dict[str, float] | None = None,
) -> float:
    if not context:
        return 0.0

    doc_text = metadata["_search_text"]
    student_text = _normalize_text(str(context.get("student_text", ""))).lower()
    support_request = _normalize_text(str(context.get("support_request", ""))).lower()
    observation_text = _normalize_text(str(context.get("observation_text", ""))).lower()
    application_reason = _normalize_text(str(context.get("application_reason", ""))).lower()
    economy_text = _normalize_text(
        " ".join(
            [
                str(context.get("basic_living_security_status", "")),
                str(context.get("student_basic_info", "")),
                str(context.get("economy_life", "")),
                str(context.get("family_status", "")),
            ]
        )
    ).lower()

    score = 0.0

    student_domains = _domain_profile_scores(student_text)
    doc_domains = _domain_profile_scores(doc_text)
    for domain, student_strength in student_domains.items():
        if student_strength <= 0:
            continue
        score += student_strength * doc_domains.get(domain, 0.0) * 0.12

    support_terms = _tokenize_query(support_request)
    if support_terms:
        score += _score_text_match(support_terms, doc_text) * 0.26

    observation_terms = _tokenize_query(observation_text)
    if observation_terms:
        score += _score_text_match(observation_terms, doc_text) * 0.20

    reason_terms = _tokenize_query(application_reason)
    if reason_terms:
        score += _score_text_match(reason_terms, doc_text) * 0.08

    if _contains_any(student_text, {"차상위", "수급", "저소득", "교육비", "납부 지연"}) and _contains_any(
        doc_text,
        LOW_INCOME_KEYWORDS,
    ):
        score += 0.12

    if not _contains_any(student_text, {"차상위", "수급", "저소득", "한부모"}) and _contains_any(
        doc_text,
        LOW_INCOME_KEYWORDS,
    ):
        score -= 0.10

    grade = int(context.get("student_grade", 0) or 0)
    if grade:
        if grade <= 6 and _contains_any(doc_text, SECONDARY_ONLY_KEYWORDS):
            score -= 0.18
        if grade <= 6 and _contains_any(doc_text, ELEMENTARY_HINT_KEYWORDS):
            score += 0.04

    student_region = str(context.get("student_region", "")).strip()
    score += _score_region_alignment(metadata, student_region)

    support_needs_counseling = _contains_any(
        f"{student_text} {support_request} {observation_text}",
        {"상담", "정서", "심리", "불안", "위클래스", "wee"},
    )
    support_needs_care = _contains_any(
        f"{student_text} {support_request} {observation_text}",
        {"돌봄", "방과 후", "방과후", "보호자 부재", "귀가", "공백"},
    )
    support_needs_academic = _contains_any(
        f"{student_text} {support_request} {observation_text}",
        {"학업", "학습", "기초학력", "수업", "집중력", "학습지원"},
    )
    doc_is_scholarship = "장학금" in metadata.get("srvPvsnNm", "") or "장학금" in metadata.get("servNm", "")
    doc_has_counseling = _contains_any(doc_text, DOMAIN_KEYWORDS["counseling"])
    doc_has_care = _contains_any(doc_text, DOMAIN_KEYWORDS["care"])
    doc_has_academic = _contains_any(doc_text, DOMAIN_KEYWORDS["academic"])

    if support_needs_counseling and doc_has_counseling:
        score += 0.14
    if support_needs_care and doc_has_care:
        score += 0.14
    if support_needs_academic and doc_has_academic:
        score += 0.10

    if "학교밖" not in student_text and "학교밖" not in support_request and "학교밖" in doc_text:
        score -= 0.12

    if doc_is_scholarship:
        if support_needs_counseling and not doc_has_counseling:
            score -= 0.12
        if support_needs_care and not doc_has_care:
            score -= 0.10
        if support_needs_academic and not doc_has_academic:
            score -= 0.04

    if domain_scores:
        domain_to_keywords = {
            "학업": {"학업", "학습", "기초학력", "교육비", "멘토링", "장학금"},
            "정서_심리": {"정서", "심리", "상담", "wee", "위클래스", "정신건강"},
            "사회성": {"사회성", "또래", "관계", "집단상담", "갈등"},
            "돌봄": {"돌봄", "방과후", "아이돌봄", "지역아동센터", "보호"},
            "경제": {"차상위", "수급", "저소득", "교육비", "생활비", "장학금"},
            "위기": {"위기", "긴급", "학대", "폭력", "보호시설"},
            "장애_특수": {"장애", "특수교육", "발달장애"},
        }
        dynamic_score = 0.0
        for domain, urgency in domain_scores.items():
            if domain == "분석근거":
                continue
            try:
                urgency_value = float(urgency)
            except (TypeError, ValueError):
                continue
            if urgency_value < 0.3:
                continue
            if _contains_any(doc_text, domain_to_keywords.get(domain, set())):
                dynamic_score += urgency_value * 0.10
        score += min(0.30, dynamic_score)

    return score


def _rank_documents(
    documents: list[dict[str, Any]],
    query: str,
    top_k: int,
    context: dict[str, Any] | None = None,
    vector_scores: dict[str, float] | None = None,
    domain_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    query_terms = _tokenize_query(query)
    vector_scores = vector_scores or {}
    scored_docs: list[dict[str, Any]] = []

    for document in documents:
        metadata = document["metadata"]
        lexical_score = (_weighted_row_match_score(query_terms, metadata) * 0.58) + (
            _score_text_match(query_terms, metadata["_search_text"]) * 0.17
        )
        context_score = _score_context_alignment(metadata, context, domain_scores=domain_scores)
        vector_score = vector_scores.get(metadata["servId"], 0.0) * 0.17
        final_score = max(0.0, min(1.0, lexical_score + context_score + vector_score))

        scored_docs.append(
            {
                "distance": round(1.0 - final_score, 6),
                "relevance_score": round(final_score, 6),
                **{k: v for k, v in metadata.items() if not k.startswith("_")},
            }
        )

    scored_docs.sort(
        key=lambda item: (
            item["relevance_score"],
            _safe_int(item.get("inqNum", "0")),
            item.get("servNm", ""),
        ),
        reverse=True,
    )

    min_score = max(0.0, min(1.0, settings.rag_min_recommendation_score))
    filtered_docs = [item for item in scored_docs if item["relevance_score"] >= min_score]
    selected = filtered_docs if len(filtered_docs) >= top_k else scored_docs
    return selected[:top_k]


def _fallback_similarity_search(
    documents: list[dict[str, Any]],
    query: str,
    top_k: int,
    context: dict[str, Any] | None = None,
    domain_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    return _rank_documents(
        documents=documents,
        query=query,
        top_k=top_k,
        context=context,
        domain_scores=domain_scores,
    )


def _build_vectorstore(documents: list[dict[str, Any]]) -> Any:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Add it to .env before using embeddings.")

    embeddings = GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embedding_model,
        google_api_key=api_key,
    )
    lc_documents = [
        Document(
            page_content=document["page_content"],
            metadata={k: v for k, v in document["metadata"].items() if not k.startswith("_")},
        )
        for document in documents
    ]
    return FAISS.from_documents(lc_documents, embeddings)


def search_relevant_institutions(
    query: str,
    top_k: int | None = None,
    csv_path: str | Path | None = None,
    context: dict[str, Any] | None = None,
    domain_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("Query text is empty.")

    resolved_top_k = top_k or settings.rag_top_k
    if resolved_top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    if csv_path is None:
        csv_paths = _parse_csv_list(settings.rag_data_files)
    else:
        csv_paths = [_resolve_path(csv_path)]

    if not csv_paths:
        raise ValueError("No RAG CSV files are configured.")

    documents = _load_documents(csv_paths)

    if not settings.use_gemini_embeddings:
        return _fallback_similarity_search(
            documents=documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
        )

    try:
        vectorstore = _build_vectorstore(documents)
        results = vectorstore.similarity_search_with_score(
            query,
            k=min(len(documents), max(resolved_top_k * 3, 50)),
        )
        vector_scores: dict[str, float] = {}
        for doc, distance in results:
            serv_id = str(doc.metadata.get("servId", "")).strip()
            if not serv_id:
                continue
            relevance_score = 1 / (1 + float(distance))
            vector_scores[serv_id] = max(vector_scores.get(serv_id, 0.0), relevance_score)

        return _rank_documents(
            documents=documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            vector_scores=vector_scores,
            domain_scores=domain_scores,
        )
    except Exception:
        return _fallback_similarity_search(
            documents=documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
        )
