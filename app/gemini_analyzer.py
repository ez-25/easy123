import json
import re
import ssl
import time
from typing import Any
from urllib.parse import quote
from urllib import error as urlerror
from urllib import request as urlrequest

import certifi
from pydantic import ValidationError

from app.config import settings
from app.models import (
    AnalyzeStudentRequest,
    GeminiAnalysisResult,
    estimate_age_from_school_grade,
    infer_birth_year_from_school_grade,
)

SYSTEM_INSTRUCTION = (
    "너는 초/중/고등학교의 전문 상담 교사 겸 데이터 분석가야. "
    "학생의 기본 환경과 교사들의 관찰 일지를 종합하여 학생이 현재 겪고 있는 핵심 문제를 파악하고, "
    "어떤 지원(정서, 학업, 경제 등)이 필요한지 2~3문장으로 요약해. "
    "그리고 가장 핵심이 되는 키워드(예: 정서 안정 지원 필요, 돌봄 공백 등)를 추출해. "
    "반드시 JSON만 반환하고, 설명 문장은 쓰지 마."
)

DOMAIN_ANALYSIS_INSTRUCTION = (
    "너는 학생 복지 전문가야. "
    "교사 관찰일지를 읽고 학생에게 어떤 영역의 지원이 얼마나 긴급하게 필요한지 "
    "0.0~1.0 사이 점수로 평가해. "
    "반드시 JSON만 반환하고 설명은 쓰지 마."
)

LOCAL_SIGNAL_RULES: dict[str, set[str]] = {
    "학업 지원 필요": {"기초학력", "학습", "수업", "집중", "숙제", "학업", "참여 저조"},
    "정서 안정 지원 필요": {"불안", "눈물", "우울", "감정", "정서", "분노", "위축"},
    "또래관계 지원 필요": {"갈등", "말다툼", "친구", "또래", "사회성", "관계"},
    "돌봄 공백 지원 필요": {"돌봄", "보호자 부재", "혼자", "방과 후", "귀가", "공백"},
    "경제 지원 검토 필요": {"차상위", "수급", "교육비", "납부 지연", "저소득", "생계"},
    "위기 개입 검토 필요": {"자해", "학대", "가출", "폭력", "긴급", "위기"},
}


def _is_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "429" in message
        or "resource_exhausted" in message
        or "too many requests" in message
        or "quota" in message
    )


def _extract_keywords(text: str, limit: int = 3) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= limit:
            break
    return result


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _extract_local_signals(request_data: AnalyzeStudentRequest) -> list[str]:
    info = request_data.all_data.integrated_application_info
    difficulties = info.student_condition.student_difficulties
    observation_text = " ".join(
        f"{log.content} {log.special_notes}" for log in request_data.all_data.observation_logs
    )
    merged_text = _normalize_spaces(
        " ".join(
            [
                info.support_request,
                info.application_reason,
                info.student_personal_info.school_level,
                info.student_condition.student_status,
                difficulties.academics,
                difficulties.emotional_psychological,
                difficulties.care_safety_health,
                difficulties.economy_life,
                difficulties.etc,
                observation_text,
                info.home_environment_and_eligibility.student_basic_info,
                info.home_environment_and_eligibility.basic_living_security_status,
                info.home_environment_and_eligibility.family_status,
            ]
        )
    )

    signals: list[str] = []
    for signal, keywords in LOCAL_SIGNAL_RULES.items():
        if any(keyword in merged_text for keyword in keywords):
            signals.append(signal)
    return signals[:5]


def _build_local_summary(request_data: AnalyzeStudentRequest, local_signals: list[str]) -> str:
    info = request_data.all_data.integrated_application_info
    difficulties = info.student_condition.student_difficulties
    key_points: list[str] = []

    if any("정서" in signal or "위기" in signal for signal in local_signals):
        key_points.append("정서적 불안과 행동 조절 어려움이 반복 관찰됩니다")
    if any("학업" in signal for signal in local_signals):
        key_points.append("학업 결손과 수업 참여 저하가 함께 나타납니다")
    if any("돌봄" in signal for signal in local_signals):
        key_points.append("방과 후 돌봄 공백으로 학교 밖 시간의 보호 체계가 약합니다")
    if any("경제" in signal for signal in local_signals):
        key_points.append("가정의 경제 부담으로 교육비 지원 연계 필요성이 확인됩니다")

    if not key_points:
        key_points.append(
            f"{difficulties.academics}와 {difficulties.emotional_psychological} 문제가 함께 관찰됩니다"
        )

    support_sentence = (
        "상담, 학습, 돌봄, 복지 자원을 함께 묶는 통합 지원이 우선적으로 필요합니다."
    )
    return ". ".join(part.rstrip(".") for part in key_points[:2]) + ". " + support_sentence


def _merge_key_signals(primary: list[str], secondary: list[str], limit: int = 5) -> list[str]:
    merged: list[str] = []
    for source in (primary, secondary):
        for signal in source:
            cleaned = _normalize_spaces(signal)
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
            if len(merged) >= limit:
                return merged
    return merged


def _extract_json_object(raw_text: str) -> dict:
    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise ValueError("Empty response from Gemini.")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        return json.loads(cleaned[start : end + 1])

    raise ValueError("Could not find JSON object in Gemini response.")


def _response_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content).strip()


def _normalize_model_name(model_name: str) -> str:
    normalized = (model_name or "").strip()
    if not normalized:
        return "gemini-2.5-flash"

    aliases = {
        "gemini 3.1 flash lite": "gemini-2.5-flash-lite",
        "gemini 2.5 flash": "gemini-2.5-flash",
        "gemini 2.0 flash": "gemini-2.0-flash",
        "gemini 2.0 flash lite": "gemini-2.0-flash-lite",
    }
    key = normalized.lower()
    if key in aliases:
        return aliases[key]
    return normalized


def _gemini_generate_content(prompt: str, model_name: str, api_key: str) -> dict[str, Any]:
    safe_model_name = _normalize_model_name(model_name)
    encoded_model_name = quote(safe_model_name, safe="")
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{encoded_model_name}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urlrequest.urlopen(req, timeout=30, context=ssl_context) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini HTTP {exc.code}: {body}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Gemini network error: {exc.reason}") from exc


def _extract_text_from_gemini_response(response_body: dict[str, Any]) -> str:
    candidates = response_body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini returned no candidates.")
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    return _response_to_text(parts)


def _normalize_gemini_payload(raw_payload: dict, fallback_name: str) -> dict:
    if fallback_name == "익명 학생":
        name = fallback_name
    else:
        name = (
            raw_payload.get("이름")
            or raw_payload.get("name")
            or raw_payload.get("학생이름")
            or fallback_name
        )
    analysis = (
        raw_payload.get("분석내용")
        or raw_payload.get("요약분석")
        or raw_payload.get("analysis")
        or raw_payload.get("summary")
        or ""
    )
    key_signals = (
        raw_payload.get("핵심신호")
        or raw_payload.get("key_signals")
        or raw_payload.get("키워드")
        or []
    )

    if isinstance(key_signals, str):
        key_signals = [part.strip() for part in re.split(r"[,/|]", key_signals) if part.strip()]
    if not isinstance(key_signals, list):
        key_signals = []

    normalized_signals: list[str] = []
    for signal in key_signals:
        if not isinstance(signal, str):
            continue
        token = signal.strip()
        if token and token not in normalized_signals:
            normalized_signals.append(token)
        if len(normalized_signals) >= 5:
            break

    if len(normalized_signals) < 3:
        normalized_signals.extend(
            keyword
            for keyword in ["기초 학력 미달", "정서 불안", "돌봄 공백"]
            if keyword not in normalized_signals
        )

    return {
        "이름": str(name).strip() or fallback_name,
        "분석내용": str(analysis).strip(),
        "핵심신호": normalized_signals[:5],
    }


def _build_compact_student_context(request_data: AnalyzeStudentRequest) -> str:
    info = request_data.all_data.integrated_application_info
    personal = info.student_personal_info
    difficulties = info.student_condition.student_difficulties
    estimated_birth_year = infer_birth_year_from_school_grade(
        personal.school_level,
        personal.grade,
    )
    estimated_age = estimate_age_from_school_grade(
        personal.school_level,
        personal.grade,
    )

    observation_lines: list[str] = []
    for log in request_data.all_data.observation_logs[:3]:
        observation_lines.append(
            f"- {log.date} {log.time} {log.place}: {log.content} / 특이사항: {log.special_notes}"
        )

    return (
        f"지역: {personal.region}\n"
        f"학교급: {personal.school_level}\n"
        f"학년/반: {personal.grade}학년 {personal.class_number}반\n"
        f"추정출생연도: {estimated_birth_year or ''}\n"
        f"추정나이: {estimated_age or ''}\n"
        f"가정환경: {info.home_environment_and_eligibility.student_basic_info}, "
        f"{info.home_environment_and_eligibility.family_status}\n"
        f"지원요청: {info.support_request}\n"
        f"학생현황: {info.student_condition.student_status}\n"
        f"학생어려움(학업): {difficulties.academics}\n"
        f"학생어려움(심리정서): {difficulties.emotional_psychological}\n"
        f"학생어려움(돌봄안전건강): {difficulties.care_safety_health}\n"
        f"관찰일지:\n" + "\n".join(observation_lines)
    )


def _default_domain_scores() -> dict[str, float]:
    """Gemini 호출 실패 시 사용하는 기본 도메인 점수."""
    return {
        "학업": 0.5,
        "정서_심리": 0.5,
        "사회성": 0.3,
        "돌봄": 0.3,
        "경제": 0.1,
        "위기": 0.0,
        "장애_특수": 0.0,
        "분석근거": "",
    }


def _local_domain_scores_from_text(text: str) -> dict[str, float]:
    normalized = _normalize_spaces(text)
    return {
        "학업": 0.9 if any(keyword in normalized for keyword in {"기초학력", "학습", "수업", "집중"}) else 0.2,
        "정서_심리": 0.95 if any(keyword in normalized for keyword in {"불안", "눈물", "정서", "감정", "우울"}) else 0.2,
        "사회성": 0.75 if any(keyword in normalized for keyword in {"갈등", "친구", "말다툼", "사회성"}) else 0.15,
        "돌봄": 0.9 if any(keyword in normalized for keyword in {"돌봄", "보호자 부재", "방과 후", "공백"}) else 0.15,
        "경제": 0.8 if any(keyword in normalized for keyword in {"차상위", "수급", "교육비", "납부 지연"}) else 0.1,
        "위기": 0.8 if any(keyword in normalized for keyword in {"긴급", "자해", "학대", "폭력", "가출"}) else 0.05,
        "장애_특수": 0.7 if any(keyword in normalized for keyword in {"특수교육", "발달장애", "장애"}) else 0.0,
        "분석근거": normalized[:120],
    }


def analyze_observation_domains(
    observation_logs: list,
    student_context: str = "",
) -> dict[str, float]:
    """
    관찰일지를 Gemini로 분석하여 도메인별 긴급도 점수(0.0~1.0)를 반환한다.
    Gemini 호출 실패 시 기본값을 반환하여 서비스 중단을 방지한다.
    """
    if not settings.gemini_api_key:
        heuristic_text = " ".join(
            [
                student_context,
                " ".join(
                    f"{log.content} {log.special_notes}"
                    for log in observation_logs[:5]
                ),
            ]
        )
        return _local_domain_scores_from_text(heuristic_text)

    log_text = "\n".join(
        f"[{log.date} {log.place}] {log.content} / 특이사항: {log.special_notes}"
        for log in observation_logs[:5]
    )

    prompt = (
        f"{DOMAIN_ANALYSIS_INSTRUCTION}\n\n"
        "관찰일지:\n"
        f"{log_text}\n\n"
        "학생 기본 맥락:\n"
        f"{student_context}\n\n"
        "아래 스키마로 반환해:\n"
        "{\n"
        '  "학업": 0.0,          // 학습부진, 기초학력, 집중력\n'
        '  "정서_심리": 0.0,     // 불안, 무기력, 자존감, 분노\n'
        '  "사회성": 0.0,        // 또래갈등, 충동, 관계 어려움\n'
        '  "돌봄": 0.0,          // 방과후 공백, 혼자 있는 시간\n'
        '  "경제": 0.0,          // 경제적 어려움, 교육비\n'
        '  "위기": 0.0,          // 자해, 학대, 가출, 고위험\n'
        '  "장애_특수": 0.0,     // 발달장애, 특수교육 필요\n'
        '  "분석근거": ""        // 왜 이렇게 판단했는지 한 문장\n'
        "}"
    )

    try:
        response_body = _gemini_generate_content(
            prompt=prompt,
            model_name=settings.gemini_model,
            api_key=settings.gemini_api_key,
        )
        raw_text = _extract_text_from_gemini_response(response_body)
        parsed = _extract_json_object(raw_text)

        domain_keys = ["학업", "정서_심리", "사회성", "돌봄", "경제", "위기", "장애_특수"]
        scores: dict[str, float] = {}
        for key in domain_keys:
            val = parsed.get(key, 0.0)
            try:
                scores[key] = max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                scores[key] = 0.0

        scores["분석근거"] = str(parsed.get("분석근거", ""))
        return scores

    except Exception:
        # Gemini 실패해도 서비스 중단 없이 기본값으로 계속
        heuristic_text = " ".join(
            [
                student_context,
                " ".join(
                    f"{log.content} {log.special_notes}"
                    for log in observation_logs[:5]
                ),
            ]
        )
        return _local_domain_scores_from_text(heuristic_text)


def analyze_student_data(request_data: AnalyzeStudentRequest) -> GeminiAnalysisResult:
    local_signals = _extract_local_signals(request_data)
    local_summary = _build_local_summary(request_data, local_signals)

    if not settings.gemini_api_key:
        return _build_local_fallback_analysis(request_data, None, [])
    compact_context = _build_compact_student_context(request_data)
    prompt = (
        f"{SYSTEM_INSTRUCTION}\n\n"
        "아래 학생 데이터를 분석하고 반드시 JSON만 반환해.\n"
        "스키마:\n"
        "{\n"
        '  "이름": "익명 학생",\n'
        '  "분석내용": "[분석 결과 텍스트]",\n'
        '  "핵심신호": ["키워드1", "키워드2", "키워드3"]\n'
        "}\n\n"
        "학생 데이터:\n"
        f"{compact_context}"
    )

    model_candidates = [
        settings.gemini_model,
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
    ]
    tried_models: list[str] = []
    last_error: Exception | None = None
    had_rate_limit = False

    for model_name in model_candidates:
        if model_name in tried_models:
            continue
        tried_models.append(model_name)
        try:
            max_attempts = max(1, settings.gemini_max_retries + 1)
            for attempt in range(max_attempts):
                try:
                    response_body = _gemini_generate_content(
                        prompt=prompt,
                        model_name=model_name,
                        api_key=settings.gemini_api_key,
                    )
                    raw_text = _extract_text_from_gemini_response(response_body)
                    parsed = _extract_json_object(raw_text)
                    normalized = _normalize_gemini_payload(
                        parsed,
                        fallback_name=request_data.all_data.integrated_application_info.student_personal_info.student_name,
                    )
                    merged_signals = _merge_key_signals(normalized["핵심신호"], local_signals)
                    normalized["핵심신호"] = merged_signals
                    if not normalized["분석내용"]:
                        normalized["분석내용"] = local_summary
                    elif local_signals:
                        normalized["분석내용"] = (
                            f"{normalized['분석내용']} "
                            f"우선 지원 축은 {', '.join(merged_signals[:3])}입니다."
                        ).strip()
                    return GeminiAnalysisResult.model_validate(normalized)
                except (ValueError, ValidationError) as error:
                    last_error = error
                    if attempt == max_attempts - 1:
                        raise
                except RuntimeError as error:
                    last_error = error
                    had_rate_limit = had_rate_limit or _is_rate_limit_error(error)
                    if _is_rate_limit_error(error) and attempt < max_attempts - 1:
                        time.sleep(1 + attempt)
                        continue
                    raise
        except (RuntimeError, ValueError, ValidationError) as error:
            last_error = error
            had_rate_limit = had_rate_limit or _is_rate_limit_error(error)
            continue

    if not settings.allow_local_fallback:
        if had_rate_limit:
            raise RuntimeError(
                "Gemini quota exceeded. API-generated analysis is unavailable until quota resets "
                "or billing is enabled."
            ) from last_error
        raise RuntimeError(
            "Gemini analysis failed (model unavailable or invalid response). "
            f"Last error: {last_error}. "
            "Set ALLOW_LOCAL_FALLBACK=true only if you want deterministic local fallback."
        ) from last_error

    return _build_local_fallback_analysis(request_data, last_error, tried_models)


def _build_local_fallback_analysis(
    request_data: AnalyzeStudentRequest,
    last_error: Exception | None,
    tried_models: list[str],
) -> GeminiAnalysisResult:
    info = request_data.all_data.integrated_application_info
    name = info.student_personal_info.student_name
    difficulties = info.student_condition.student_difficulties
    local_signals = _extract_local_signals(request_data)
    key_signals = _merge_key_signals(
        local_signals,
        ["학업 지원 필요", "정서 안정 지원 필요", "돌봄 공백 지원 필요"],
    )
    observation_keywords: list[str] = []
    for log in request_data.all_data.observation_logs:
        observation_keywords.extend(_extract_keywords(log.special_notes, limit=2))
        if len(observation_keywords) >= 2:
            break
    for keyword in observation_keywords:
        if keyword not in key_signals and len(key_signals) < 5:
            key_signals.append(keyword)

    analysis = _build_local_summary(request_data, key_signals)

    return GeminiAnalysisResult(
        이름=name,
        분석내용=analysis,
        핵심신호=key_signals,
    )
