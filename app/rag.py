import csv
import os
import re
from datetime import date, datetime
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
QUERY_FIELD_WEIGHTS: dict[str, float] = {
    "servNm": 2.8,
    "lifeArray": 1.3,
    "servDgst": 2.9,
    "srvPvsnNm": 1.2,
    "intrsThemaArray": 1.0,
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
    "내용",
    "사항",
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
REGION_PATTERN = re.compile(r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)")
LOCAL_SERVICE_KEYWORDS = {
    "센터",
    "복지관",
    "상담복지센터",
    "정신건강복지센터",
    "청소년상담복지센터",
    "학교밖청소년지원센터",
    "수련관",
}
NATIONWIDE_KEYWORDS = {"전국", "전국단위", "전국 공통", "중앙부처", "전국 누구나", "전국민"}
SEXUALITY_SERVICE_KEYWORDS = {"성문화센터", "성교육", "성폭력", "성상담", "성범죄", "디지털성범죄"}
SEXUALITY_NEED_KEYWORDS = {"성폭력", "성교육", "성상담", "성범죄", "디지털성범죄", "임신", "성문제"}
LOCAL_RESTRICTION_KEYWORDS = {
    "관내",
    "소재학교",
    "소재 학교",
    "거주",
    "주민등록",
    "지역연고",
    "주변지역",
    "발전소",
    "원자력",
    "댐",
    "반경",
    "읍",
    "면",
    "소재",
    "폐광지역",
    "도서 벽지",
}
LOW_INCOME_KEYWORDS = {"차상위", "수급", "저소득", "교육비", "납부 지연", "기초생활", "생활보호"}
SERVICE_TAG_KEYWORDS: dict[str, set[str]] = {
    "academic": {"학업", "학습", "기초학력", "교육", "학비", "교육비", "멘토링", "학교"},
    "counseling": {"상담", "심리", "정서", "정신건강", "wee", "위클래스", "치유"},
    "social": {"또래", "사회성", "관계", "갈등", "대인관계", "집단상담"},
    "care": {"돌봄", "방과후", "방과 후", "아이돌봄", "보호", "지역아동센터", "아카데미"},
    "economic": {"장학금", "저소득", "차상위", "수급", "생활비", "급여", "바우처"},
    "risk": {"위기", "긴급", "학대", "폭력", "보호시설", "가출"},
}
SCHOOL_STAGE_RULES: dict[str, tuple[int, int]] = {
    "elementary": (1, 6),
    "middle": (7, 9),
    "high": (10, 12),
}
HIGH_SCHOOL_KEYWORDS = {
    "고등학생",
    "고등학교",
    "고교",
    "고등",
    "일반계고",
    "과학고",
    "국제고",
    "마이스터고",
    "영재고",
    "예술고",
    "외국어고",
    "일반고",
    "체육고",
    "특성화고",
    "자율고",
}
MIDDLE_SCHOOL_KEYWORDS = {"중학생", "중학교", "중등"}
ELEMENTARY_SCHOOL_KEYWORDS = {"초등학생", "초등학교", "초등"}
CONDITIONAL_ELIGIBILITY_KEYWORDS: dict[str, set[str]] = {
    "worker": {"근로청소년", "산업체 근로", "근로자", "직장"},
    "disabled_family": {"장애인", "중증장애", "장애인 가족"},
    "multicultural_family": {"다문화", "다문화가족"},
    "patriot_veteran": {"국가유공자", "보훈", "의사상자", "유족"},
    "youth_leader_child": {"청소년지도위원", "청소년지도협의회"},
    "talent_award": {"특기생", "예체능", "기능/체육/예능", "대회", "입상", "재능이 뛰어난"},
    "school_outside": {"학교밖", "학업중단", "자퇴", "검정고시"},
    "opportunity_admission": {"기회균등전형", "기회균등", "사회통합전형", "특목고"},
    "teen_parent": {"청소년한부모", "청소년 한부모"},
    "single_parent_family": {"한부모가족", "법정 한부모"},
    "multi_child_family": {"다자녀"},
    "orphan_head_household": {"소년소녀가장"},
    "union_member_family": {"조합원", "신협", "공제"},
    "seafarer_family": {"선원", "승무경력", "선사"},
    "power_plant_resident": {"발전소", "원자력", "화력본부", "댐", "주변지역", "반경"},
    "academic_excellence": {"성적우수", "석차", "성적의", "직전학기 성적", "학교석차"},
    "grade_merit": {"내신", "등급 평균", "전국연합학력평가", "학업 성적", "상위 50%"},
    "property_tax_limit": {"재산세"},
    "arts_major": {"발레", "전공생"},
    "environment_worker_family": {"환경미화원"},
    "special_education": {"특수교육대상자", "장애학생", "경계선지능", "난독", "난산"},
    "remote_area": {"폐광지역", "도서 벽지"},
}
AGE_KEYWORD_RULES: tuple[tuple[str, int, int], ...] = (
    ("영유아", 0, 6),
    ("유아", 0, 6),
    ("아동", 6, 12),
    ("초등", 7, 13),
    ("초등학생", 7, 13),
    ("중학생", 13, 16),
    ("중학교", 13, 16),
    ("고등학생", 16, 19),
    ("고등학교", 16, 19),
    ("대학생", 19, 29),
    ("청소년", 7, 24),
    ("청년", 19, 34),
)
DEFAULT_SCORE_THRESHOLD = 1.8


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
    return [_resolve_path(item.strip()) for item in raw.split(",") if item.strip()]


def _safe_int(value: str) -> int:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(text: str) -> list[str]:
    terms = re.findall(r"[가-힣A-Za-z0-9]{2,}", _normalize_text(text).lower())
    deduped: list[str] = []
    for term in terms:
        if term in KOREAN_STOPWORDS:
            continue
        if term not in deduped:
            deduped.append(term)
    return deduped


def _contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize_region_name(region: str) -> str:
    cleaned = _normalize_text(region)
    if not cleaned:
        return ""
    for canonical, aliases in REGION_ALIASES.items():
        if any(cleaned == alias or cleaned.startswith(alias) for alias in aliases):
            return canonical
    return cleaned


def _extract_region_tokens(region: str) -> list[str]:
    cleaned = _normalize_text(region)
    if not cleaned:
        return []
    tokens = list(dict.fromkeys(REGION_PATTERN.findall(cleaned)))
    canonical = _normalize_region_name(cleaned)
    result: list[str] = []
    if canonical:
        result.append(canonical)
    for token in tokens:
        if token not in result:
            result.append(token)
    return result


def _extract_declared_regions(text: str) -> list[str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return []
    result: list[str] = []
    canonical = _normalize_region_name(cleaned)
    if canonical and canonical != cleaned:
        result.append(canonical)
    for match in REGION_PATTERN.findall(cleaned):
        if match not in result:
            result.append(match)
    return result


def _parse_birth_date(value: str) -> date | None:
    cleaned = _normalize_text(value)
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _calculate_age(birth_date: str) -> int | None:
    parsed = _parse_birth_date(birth_date)
    if parsed is None:
        return None
    today = date.today()
    return today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))


def _infer_age_bounds(text: str) -> tuple[int | None, int | None]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return None, None

    min_age: int | None = None
    max_age: int | None = None

    for low, high in re.findall(r"만?\s*(\d{1,2})\s*세\s*(?:~|-|부터)\s*만?\s*(\d{1,2})\s*세", cleaned):
        low_value = int(low)
        high_value = int(high)
        min_age = low_value if min_age is None else max(min_age, low_value)
        max_age = high_value if max_age is None else min(max_age, high_value)

    for value, operator in re.findall(r"만?\s*(\d{1,2})\s*세\s*(이하|미만|이상|초과)", cleaned):
        age_value = int(value)
        if operator == "이하":
            max_age = age_value if max_age is None else min(max_age, age_value)
        elif operator == "미만":
            max_age = age_value - 1 if max_age is None else min(max_age, age_value - 1)
        elif operator == "이상":
            min_age = age_value if min_age is None else max(min_age, age_value)
        elif operator == "초과":
            min_age = age_value + 1 if min_age is None else max(min_age, age_value + 1)

    keyword_lows: list[int] = []
    keyword_highs: list[int] = []
    for keyword, low_value, high_value in AGE_KEYWORD_RULES:
        if keyword in cleaned:
            keyword_lows.append(low_value)
            keyword_highs.append(high_value)

    if keyword_lows:
        keyword_min = min(keyword_lows)
        keyword_max = max(keyword_highs)
        min_age = keyword_min if min_age is None else max(min_age, keyword_min)
        max_age = keyword_max if max_age is None else min(max_age, keyword_max)

    return min_age, max_age


def _extract_service_tags(text: str) -> set[str]:
    lowered = _normalize_text(text).lower()
    tags: set[str] = set()
    for tag, keywords in SERVICE_TAG_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            tags.add(tag)
    return tags


def _extract_school_stages(text: str) -> set[str]:
    cleaned = _normalize_text(text)
    stages: set[str] = set()
    if _contains_any(cleaned, ELEMENTARY_SCHOOL_KEYWORDS):
        stages.add("elementary")
    if _contains_any(cleaned, MIDDLE_SCHOOL_KEYWORDS):
        stages.add("middle")
    if _contains_any(cleaned, HIGH_SCHOOL_KEYWORDS):
        stages.add("high")
    return stages


def _grade_to_school_stage(grade: int) -> str:
    if 1 <= grade <= 6:
        return "elementary"
    if 7 <= grade <= 9:
        return "middle"
    if 10 <= grade <= 12:
        return "high"
    return ""


def _infer_student_school_stage(text: str, grade: int, age: int | None) -> str:
    explicit_stages = _extract_school_stages(text)
    if len(explicit_stages) == 1:
        return next(iter(explicit_stages))

    if age is not None:
        if 7 <= age <= 12:
            return "elementary"
        if 13 <= age <= 15:
            return "middle"
        if 16 <= age <= 18:
            return "high"

    return _grade_to_school_stage(grade)


def _extract_required_eligibilities(text: str) -> set[str]:
    cleaned = _normalize_text(text)
    required: set[str] = set()
    for eligibility, keywords in CONDITIONAL_ELIGIBILITY_KEYWORDS.items():
        if any(keyword in cleaned for keyword in keywords):
            required.add(eligibility)
    return required


def _extract_student_eligibilities(text: str) -> set[str]:
    cleaned = _normalize_text(text)
    eligibilities: set[str] = set()
    if any(keyword in cleaned for keyword in LOW_INCOME_KEYWORDS):
        eligibilities.add("low_income")
    for eligibility, keywords in CONDITIONAL_ELIGIBILITY_KEYWORDS.items():
        if any(keyword in cleaned for keyword in keywords):
            eligibilities.add(eligibility)
    return eligibilities


def _is_region_restricted(metadata: dict[str, Any], combined_text: str) -> bool:
    if metadata["welfareType"] == "중앙부처":
        return False
    if metadata["category"] == "기관":
        return True
    if "지역연고" in metadata["srvPvsnNm"]:
        return True
    if _contains_any(combined_text, LOCAL_RESTRICTION_KEYWORDS):
        return True
    return metadata["welfareType"] in {"지자체", "지자체(출자출연기관)"}


def _is_restricted_scholarship(metadata: dict[str, Any], combined_text: str) -> bool:
    if "장학금" not in combined_text:
        return False
    if metadata["welfareType"] == "중앙부처" or _contains_any(combined_text, NATIONWIDE_KEYWORDS):
        return False
    if _contains_any(combined_text, LOCAL_RESTRICTION_KEYWORDS):
        return True
    return bool(metadata["_required_eligibilities"]) or metadata["welfareType"] != "중앙부처"


def _build_searchable_text(metadata: dict[str, str]) -> str:
    return " ".join(_normalize_text(metadata.get(column, "")) for column in NORMALIZED_COLUMNS).lower()


def _normalize_row(row: dict[str, str], source_dataset: str) -> dict[str, Any]:
    region = _normalize_text(row.get("region", "") or row.get("agency", "") or row.get("department", ""))
    metadata: dict[str, Any] = {
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
    combined_text = " ".join(
        [
            metadata["servNm"],
            metadata["region"],
            metadata["agency"],
            metadata["department"],
            metadata["intrsThemaArray"],
            metadata["lifeArray"],
            metadata["srvPvsnNm"],
            metadata["servDgst"],
        ]
    )
    service_text = " ".join(
        [
            metadata["servNm"],
            metadata["intrsThemaArray"],
            metadata["lifeArray"],
            metadata["srvPvsnNm"],
            metadata["servDgst"],
        ]
    )
    metadata["_search_text"] = _build_searchable_text(metadata)
    metadata["_region_tokens"] = _extract_declared_regions(combined_text)
    metadata["_age_min"], metadata["_age_max"] = _infer_age_bounds(combined_text)
    metadata["_tags"] = _extract_service_tags(service_text)
    metadata["_school_stages"] = _extract_school_stages(combined_text)
    metadata["_required_eligibilities"] = _extract_required_eligibilities(combined_text)
    metadata["_is_local_institution"] = source_dataset == "integrated_institution_data.csv"
    metadata["_is_scholarship"] = "장학금" in combined_text
    metadata["_is_region_restricted"] = _is_region_restricted(metadata, combined_text)
    metadata["_is_restricted_scholarship"] = _is_restricted_scholarship(metadata, combined_text)
    metadata["_is_nationwide"] = (
        _contains_any(combined_text, NATIONWIDE_KEYWORDS)
        and not metadata["_region_tokens"]
        and not metadata["_is_region_restricted"]
        and not metadata["_is_restricted_scholarship"]
    )
    metadata["_requires_local_region"] = metadata["_is_local_institution"] or metadata["_is_region_restricted"] or (
        metadata["_is_restricted_scholarship"]
        or bool(metadata["_region_tokens"]) and not metadata["_is_nationwide"]
    )
    metadata["_is_school_outside_support"] = "school_outside" in metadata["_required_eligibilities"]
    metadata["_is_sexuality_service"] = _contains_any(combined_text, SEXUALITY_SERVICE_KEYWORDS)
    metadata["_is_direct_service"] = any(
        keyword in combined_text for keyword in {"상담", "서비스", "프로그램", "돌봄", "보호", "연계", "센터"}
    ) and "장학금" not in combined_text
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
                unique_id = metadata["servId"] or f"{metadata['servNm']}|{metadata['servDgst']}"
                dedupe_key = (metadata["sourceDataset"], unique_id, metadata["servNm"])
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                documents.append({"metadata": metadata, "page_content": metadata["_search_text"]})

    if not documents:
        raise ValueError("No records found in configured CSV files.")
    return documents


def _build_student_profile(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}
    student_text = _normalize_text(str(context.get("student_text", "")))
    support_request = _normalize_text(str(context.get("support_request", "")))
    observation_text = _normalize_text(str(context.get("observation_text", "")))
    school_level = _normalize_text(str(context.get("student_school_level", "")))
    region = _normalize_text(str(context.get("student_region", "")))
    birth_date = _normalize_text(str(context.get("student_birth_date", "")))
    age = _calculate_age(birth_date)

    difficulty_text = " ".join(
        [
            student_text,
            school_level,
            support_request,
            observation_text,
            _normalize_text(str(context.get("application_reason", ""))),
            _normalize_text(str(context.get("economy_life", ""))),
            _normalize_text(str(context.get("basic_living_security_status", ""))),
        ]
    ).lower()

    need_tags = _extract_service_tags(difficulty_text)
    if "교우" in difficulty_text or "친구" in difficulty_text:
        need_tags.add("social")
    if "교육비" in difficulty_text or "차상위" in difficulty_text or "수급" in difficulty_text:
        need_tags.add("economic")

    observation_terms = _tokenize(observation_text)
    summary_terms = _tokenize(student_text + " " + support_request)
    grade = int(context.get("student_grade", 0) or 0)
    student_stage = _infer_student_school_stage(f"{school_level} {difficulty_text}", grade, age)
    student_eligibilities = _extract_student_eligibilities(difficulty_text)

    return {
        "age": age,
        "region": region,
        "region_tokens": _extract_region_tokens(region),
        "canonical_region": _normalize_region_name(region),
        "need_tags": need_tags,
        "priority_tags": _extract_service_tags(f"{support_request} {observation_text}".lower()),
        "observation_terms": observation_terms,
        "summary_terms": summary_terms,
        "student_grade": grade,
        "student_school_level": school_level,
        "school_stage": student_stage,
        "student_eligibilities": student_eligibilities,
        "difficulty_text": difficulty_text,
    }


def _is_region_eligible(metadata: dict[str, Any], profile: dict[str, Any]) -> bool:
    student_region = profile["region"]
    student_tokens = profile["region_tokens"]
    canonical_region = profile["canonical_region"]
    if not student_region:
        return True

    doc_regions = metadata.get("_region_tokens", [])
    doc_text = " ".join(
        [
            metadata.get("region", ""),
            metadata.get("agency", ""),
            metadata.get("department", ""),
            metadata.get("servDgst", ""),
        ]
    )

    if metadata.get("_is_nationwide"):
        return True

    if metadata.get("_is_local_institution"):
        if canonical_region and any(canonical_region == _normalize_region_name(token) for token in doc_regions):
            return True
        if doc_regions:
            return False
        return any(re.search(rf"(^|\\s){re.escape(token)}($|\\s)", doc_text) for token in student_tokens if token)

    if not metadata.get("_requires_local_region"):
        return True

    if canonical_region and any(canonical_region == _normalize_region_name(token) for token in doc_regions):
        return True
    if doc_regions:
        return False
    return any(re.search(rf"(^|\\s){re.escape(token)}($|\\s)", doc_text) for token in student_tokens if token)


def _is_age_eligible(metadata: dict[str, Any], profile: dict[str, Any]) -> bool:
    age = profile["age"]
    if age is None:
        return True

    min_age = metadata.get("_age_min")
    max_age = metadata.get("_age_max")
    if min_age is not None and age < min_age:
        return False
    if max_age is not None and age > max_age:
        return False

    doc_text = metadata["_search_text"]
    if age >= 25 and _contains_any(doc_text, {"초등학생", "중학생", "고등학생", "초중고"}):
        return False
    if age <= 12 and _contains_any(doc_text, {"대학생", "청년"}):
        return False
    return True


def _is_age_eligible_relaxed(metadata: dict[str, Any], profile: dict[str, Any]) -> bool:
    age = profile["age"]
    if age is None:
        return True

    if _is_age_eligible(metadata, profile):
        return True

    doc_text = metadata["_search_text"]
    if 7 <= age <= 12 and "청소년" in doc_text and not _contains_any(doc_text, {"고등학생", "중학생", "대학생", "청년"}):
        return True
    return False


def _is_school_stage_eligible(metadata: dict[str, Any], profile: dict[str, Any]) -> bool:
    doc_stages = metadata.get("_school_stages", set())
    student_stage = profile.get("school_stage", "")
    if not doc_stages or not student_stage:
        return True
    if student_stage in doc_stages:
        return True

    age = profile.get("age")
    if age is None:
        return False

    for stage in doc_stages:
        low_grade, high_grade = SCHOOL_STAGE_RULES.get(stage, (0, 0))
        if not low_grade:
            continue
        # Korean school age is not exact enough to be a hard grade conversion,
        # but this keeps obviously impossible matches out of the top results.
        low_age = low_grade + 6
        high_age = high_grade + 7
        if low_age <= age <= high_age:
            return True
    return False


def _has_required_eligibilities(metadata: dict[str, Any], profile: dict[str, Any]) -> bool:
    required = set(metadata.get("_required_eligibilities", set()))
    if not required:
        return True

    student_eligibilities = set(profile.get("student_eligibilities", set()))
    missing = required - student_eligibilities

    # Low-income eligibility is often a broad condition in scholarship data. It is
    # handled by positive scoring, while uncommon special qualifications are hard filters.
    if not missing:
        return True
    return False


def _passes_hard_filters(
    metadata: dict[str, Any],
    profile: dict[str, Any],
    relax_age: bool = False,
) -> bool:
    if not _is_school_stage_eligible(metadata, profile):
        return False

    if metadata.get("_is_school_outside_support") and "school_outside" not in profile["student_eligibilities"]:
        return False

    if metadata.get("_is_sexuality_service") and not _contains_any(profile["difficulty_text"], SEXUALITY_NEED_KEYWORDS):
        return False

    if not _has_required_eligibilities(metadata, profile):
        return False

    age_eligible = _is_age_eligible_relaxed(metadata, profile) if relax_age else _is_age_eligible(metadata, profile)
    return _is_region_eligible(metadata, profile) and age_eligible


def _field_overlap_score(query_terms: list[str], metadata: dict[str, Any]) -> float:
    if not query_terms:
        return 0.0

    score = 0.0
    total_weight = 0.0
    for field, weight in QUERY_FIELD_WEIGHTS.items():
        field_text = metadata.get(field, "").lower()
        total_weight += weight
        if not field_text:
            continue
        hit_count = sum(1 for term in query_terms if term in field_text)
        score += (hit_count / len(query_terms)) * weight
    return score / total_weight if total_weight else 0.0


def _score_candidate(
    metadata: dict[str, Any],
    query_terms: list[str],
    profile: dict[str, Any],
    domain_scores: dict[str, float] | None,
) -> float:
    doc_text = metadata["_search_text"]
    raw_score = 0.0

    raw_score += _field_overlap_score(query_terms, metadata) * 2.7

    if profile["summary_terms"]:
        summary_hits = sum(1 for term in profile["summary_terms"] if term in doc_text)
        raw_score += (summary_hits / len(profile["summary_terms"])) * 2.2

    if profile["observation_terms"]:
        observation_hits = sum(1 for term in profile["observation_terms"] if term in doc_text)
        raw_score += (observation_hits / len(profile["observation_terms"])) * 3.0

    need_tags = profile["need_tags"]
    priority_tags = profile["priority_tags"] or need_tags
    doc_tags = metadata["_tags"]
    shared_tags = need_tags & doc_tags
    raw_score += len(shared_tags) * 1.2
    raw_score += len(priority_tags & doc_tags) * 1.6

    if "counseling" in need_tags and "counseling" in doc_tags:
        raw_score += 1.6
    if "care" in need_tags and "care" in doc_tags:
        raw_score += 1.5
    if "academic" in need_tags and "academic" in doc_tags:
        raw_score += 1.1
    if "economic" in need_tags and "economic" in doc_tags:
        raw_score += 0.7

    if metadata.get("_is_local_institution"):
        raw_score += 1.0
    if metadata.get("_is_scholarship") and "economic" in need_tags:
        raw_score += 0.4
    if metadata.get("_is_scholarship") and ("counseling" in need_tags or "care" in need_tags):
        raw_score -= 1.4
    if metadata.get("_is_school_outside_support"):
        raw_score -= 1.0
    if metadata.get("_is_direct_service") and priority_tags & {"counseling", "care", "academic"}:
        raw_score += 2.0
    if metadata.get("_is_scholarship") and priority_tags & {"counseling", "care"}:
        raw_score -= 3.0
    if priority_tags and not (priority_tags & doc_tags):
        raw_score -= 1.4

    difficulty_text = profile["difficulty_text"]
    student_eligibilities = set(profile.get("student_eligibilities", set()))
    if "low_income" in student_eligibilities and _contains_any(doc_text, LOW_INCOME_KEYWORDS):
        raw_score += 2.4
    if _contains_any(difficulty_text, {"국민기초생활수급자", "법정차상위", "교육비", "경제적 어려움"}):
        if _contains_any(doc_text, {"교육급여", "교육비 지원", "고교학비", "학비", "저소득층"}):
            raw_score += 2.4
    if _contains_any(difficulty_text, {"석식", "저녁급식", "급식", "식사"}):
        if _contains_any(doc_text, {"석식", "저녁급식", "급식비"}):
            raw_score += 3.0
    if _contains_any(difficulty_text, {"방과 후", "방과후", "학습 보충", "맞춤형 학습"}):
        if _contains_any(doc_text, {"방과후학교", "자유수강권", "지역아동센터", "방과후 돌봄"}):
            raw_score += 3.0
    if _contains_any(doc_text, {"기회균등전형", "사회통합전형", "특목고"}):
        raw_score -= 4.0

    if profile["canonical_region"]:
        doc_regions = metadata.get("_region_tokens", [])
        if any(profile["canonical_region"] == _normalize_region_name(token) for token in doc_regions):
            raw_score += 1.0
        elif metadata.get("_is_nationwide"):
            raw_score += 0.2

    age = profile["age"]
    min_age = metadata.get("_age_min")
    max_age = metadata.get("_age_max")
    if age is not None and min_age is not None and max_age is not None:
        midpoint = (min_age + max_age) / 2
        spread = max(1.0, (max_age - min_age) / 2)
        age_fit = max(0.0, 1.0 - (abs(age - midpoint) / spread))
        raw_score += age_fit * 0.8

    if domain_scores:
        domain_map = {
            "학업": "academic",
            "정서_심리": "counseling",
            "사회성": "social",
            "돌봄": "care",
            "경제": "economic",
            "위기": "risk",
        }
        for domain, tag in domain_map.items():
            try:
                urgency = float(domain_scores.get(domain, 0.0))
            except (TypeError, ValueError):
                urgency = 0.0
            if urgency >= 0.3 and tag in doc_tags:
                raw_score += urgency * 1.1

    return raw_score


def _calibrate_scores(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not results:
        return results

    for item in results:
        raw_score = float(item["_raw_score"])
        normalized = raw_score / 18.0
        item["relevance_score"] = round(max(0.01, min(0.99, normalized)), 6)
        item["distance"] = round(1.0 - item["relevance_score"], 6)
        del item["_raw_score"]
    return results


def _rank_documents(
    documents: list[dict[str, Any]],
    query: str,
    top_k: int,
    context: dict[str, Any] | None = None,
    domain_scores: dict[str, float] | None = None,
    relax_age: bool = False,
) -> list[dict[str, Any]]:
    query_terms = _tokenize(query)
    profile = _build_student_profile(context)

    scored_docs: list[dict[str, Any]] = []
    fallback_docs: list[dict[str, Any]] = []

    for document in documents:
        metadata = document["metadata"]
        if not _passes_hard_filters(metadata, profile, relax_age=relax_age):
            continue

        raw_score = _score_candidate(metadata, query_terms, profile, domain_scores)
        item = {
            **{k: v for k, v in metadata.items() if not k.startswith("_")},
            "_raw_score": raw_score,
        }
        if raw_score >= DEFAULT_SCORE_THRESHOLD:
            scored_docs.append(item)
        else:
            fallback_docs.append(item)

    selected = scored_docs or fallback_docs
    selected.sort(
        key=lambda item: (
            item["_raw_score"],
            _safe_int(item.get("inqNum", "0")),
            item.get("servNm", ""),
        ),
        reverse=True,
    )
    trimmed = selected[:top_k]
    return _calibrate_scores(trimmed)


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

    csv_paths = [_resolve_path(csv_path)] if csv_path else _parse_csv_list(settings.rag_data_files)
    if not csv_paths:
        raise ValueError("No RAG CSV files are configured.")

    documents = _load_documents(csv_paths)

    if not settings.use_gemini_embeddings:
        ranked = _rank_documents(
            documents=documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
        )
        if ranked:
            return ranked
        return _rank_documents(
            documents=documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
            relax_age=True,
        )

    try:
        vectorstore = _build_vectorstore(documents)
        results = vectorstore.similarity_search_with_score(query, k=min(len(documents), max(60, resolved_top_k * 4)))
        candidate_ids = {str(doc.metadata.get("servId", "")).strip() for doc, _ in results}
        filtered_documents = [
            document for document in documents if document["metadata"].get("servId", "") in candidate_ids
        ]
        ranked = _rank_documents(
            documents=filtered_documents or documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
        )
        if ranked:
            return ranked
        return _rank_documents(
            documents=filtered_documents or documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
            relax_age=True,
        )
    except Exception:
        ranked = _rank_documents(
            documents=documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
        )
        if ranked:
            return ranked
        return _rank_documents(
            documents=documents,
            query=query,
            top_k=resolved_top_k,
            context=context,
            domain_scores=domain_scores,
            relax_age=True,
        )
