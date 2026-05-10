import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _join_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _parse_grade(value: Any) -> int:
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def _normalize_school_level(value: Any) -> str:
    return _join_value(value)


def infer_birth_year_from_school_grade(
    school_level: str,
    grade: int,
    reference_year: int | None = None,
) -> int | None:
    year = reference_year or date.today().year
    level = _normalize_school_level(school_level)
    grade_value = _parse_grade(grade)
    if grade_value <= 0:
        return None

    if "초" in level:
        total_grade = grade_value
    elif "중" in level:
        total_grade = grade_value + 6
    elif "고" in level:
        total_grade = grade_value + 9
    else:
        total_grade = grade_value

    return year - (total_grade + 6)


def estimate_age_from_school_grade(
    school_level: str,
    grade: int,
    reference_year: int | None = None,
) -> int | None:
    birth_year = infer_birth_year_from_school_grade(school_level, grade, reference_year)
    if birth_year is None:
        return None
    return (reference_year or date.today().year) - birth_year


class StudentPersonalInfo(BaseModel):
    student_name: str = Field("익명 학생", alias="학생이름")
    region: str = Field("", alias="지역")
    grade: int = Field(..., alias="학년")
    class_number: int = Field(0, alias="반")
    school_level: str = Field("", alias="학교급")
    birth_date: str = Field("", alias="생년월일")
    gender: str = Field(..., alias="성별")

    model_config = ConfigDict(extra="forbid")

    @field_validator("grade", "class_number", mode="before")
    @classmethod
    def parse_number_field(cls, value: Any) -> int:
        return _parse_grade(value)


class HomeEnvironmentAndEligibility(BaseModel):
    student_basic_info: str = Field(..., alias="학생기본사항")
    basic_living_security_status: str = Field(..., alias="기초수급보장현황")
    family_status: str = Field(..., alias="가족현황")

    model_config = ConfigDict(extra="forbid")


class StudentDifficulties(BaseModel):
    academics: str = Field(..., alias="학업")
    emotional_psychological: str = Field(..., alias="심리_정서")
    care_safety_health: str = Field(..., alias="돌봄_안전_건강")
    economy_life: str = Field(..., alias="경제_생활")
    etc: str = Field(..., alias="기타")

    model_config = ConfigDict(extra="forbid")


class StudentCondition(BaseModel):
    student_status: str = Field(..., alias="학생현황")
    student_difficulties: StudentDifficulties = Field(..., alias="학생어려움")

    model_config = ConfigDict(extra="forbid")


class IntegratedApplicationInfo(BaseModel):
    student_personal_info: StudentPersonalInfo = Field(..., alias="학생인적사항")
    home_environment_and_eligibility: HomeEnvironmentAndEligibility = Field(
        ...,
        alias="가정환경및자격",
    )
    student_condition: StudentCondition = Field(..., alias="학생상태")
    application_reason: str = Field(..., alias="신청사유")
    support_request: str = Field(..., alias="지원요청사항")

    model_config = ConfigDict(extra="forbid")


class ObservationLog(BaseModel):
    teacher_name: str = Field("", alias="교사이름")
    position: str = Field(..., alias="직위")
    date: str = Field(..., alias="날짜")
    time: str = Field(..., alias="시간")
    place: str = Field(..., alias="장소")
    content: str = Field(..., alias="내용")
    special_notes: str = Field(..., alias="특이사항")

    model_config = ConfigDict(extra="forbid")


class AllData(BaseModel):
    integrated_application_info: IntegratedApplicationInfo = Field(
        ...,
        alias="통합신청서정보",
    )
    observation_logs: list[ObservationLog] = Field(..., alias="관찰일지목록")

    model_config = ConfigDict(extra="forbid")


class AnalyzeStudentRequest(BaseModel):
    all_data: AllData = Field(..., alias="전체데이터")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def normalize_application_schema(cls, raw_data: Any) -> Any:
        if not isinstance(raw_data, dict):
            return raw_data

        all_data = raw_data.get("전체데이터")
        if not isinstance(all_data, dict):
            return raw_data
        if "통합신청서정보" in all_data:
            return raw_data

        application = all_data.get("학생맞춤통합지원_신청서")
        if not isinstance(application, dict):
            return raw_data

        student_info = application.get("대상학생_정보", {}) or {}
        basic_info = application.get("학생_기본사항", {}) or {}
        difficulties = application.get("학생_어려움", {}) or {}

        normalized = {
            "전체데이터": {
                "통합신청서정보": {
                    "학생인적사항": {
                        "학생이름": _join_value(student_info.get("성명")) or "익명 학생",
                        "학년": _parse_grade(student_info.get("학년")),
                        "반": 0,
                        "지역": _join_value(student_info.get("거주지역")),
                        "학교급": _join_value(student_info.get("학교급")),
                        "생년월일": _join_value(student_info.get("생년월일")),
                        "성별": _join_value(student_info.get("성별")),
                    },
                    "가정환경및자격": {
                        "학생기본사항": _join_value(basic_info.get("학생현황")),
                        "기초수급보장현황": _join_value(basic_info.get("기초수급_보장현황")),
                        "가족현황": _join_value(basic_info.get("가족현황")),
                    },
                    "학생상태": {
                        "학생현황": _join_value(basic_info.get("학생현황")),
                        "학생어려움": {
                            "학업": _join_value(difficulties.get("학업")),
                            "심리_정서": _join_value(difficulties.get("심리_정서")),
                            "돌봄_안전_건강": _join_value(difficulties.get("돌봄_안전_건강")),
                            "경제_생활": _join_value(difficulties.get("경제_생활")),
                            "기타": _join_value(difficulties.get("기타")),
                        },
                    },
                    "신청사유": _join_value(application.get("신청_사유")),
                    "지원요청사항": _join_value(application.get("지원_요청_사항")),
                },
                "관찰일지목록": all_data.get("관찰일지목록", []),
            }
        }
        return normalized


class AnalysisSummary(BaseModel):
    name: str = Field(..., alias="이름")
    summarized_analysis: str = Field(..., alias="요약분석")
    key_signals: list[str] = Field(..., alias="핵심신호")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class RecommendationItem(BaseModel):
    category: str
    suitability: int          # relevance_score * 100 반올림값 (0~100)
    welfareType: str
    servId: str
    servNm: str
    region: str
    agency: str
    department: str
    intrsThemaArray: list[str]
    lifeArray: list[str]
    srvPvsnNm: str
    sprtCycNm: str
    servDgst: str
    servDtlLink: str
    inqNum: int
    contact: str | None
    sourceDataset: str

    model_config = ConfigDict(extra="forbid")


class AnalyzeStudentResponse(BaseModel):
    ai_analysis_summary: AnalysisSummary = Field(..., alias="ai_분석정리_요약")
    ai_recommended_supports: list[RecommendationItem] = Field(
        ...,
        alias="ai_추천기관_제도",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class GeminiAnalysisResult(BaseModel):
    name: str = Field(..., alias="이름")
    analysis: str = Field(..., alias="분석내용")
    key_signals: list[str] = Field(..., alias="핵심신호")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)
