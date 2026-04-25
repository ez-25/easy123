import json

from app.rag import search_relevant_institutions


def run_test() -> None:
    query = "대구광역시 차상위계층 중학생 정서 불안 돌봄 공백 기초 학력 미달 방과 후 학습 지원"
    context = {
        "student_grade": 2,
        "student_region": "대구광역시",
        "student_text": (
            "차상위계층 중학생. 정서 불안, 수업 집중력 부족, 방과 후 돌봄 공백, "
            "교육비 납부 지연, 교우 갈등, 상담 및 방과 후 학습 지원 필요."
        ),
        "support_request": "전문 상담 및 방과 후 학습 지원 연계",
        "application_reason": "정서적 불안 및 돌발 행동",
        "observation_text": "교실 배회, 말다툼, 눈물, 집중력 저하, 긴급 돌봄 연계 검토 필요",
        "basic_living_security_status": "차상위계층",
        "student_basic_info": "할머니와 거주 중",
        "family_status": "할머니, 여동생",
        "economy_life": "체험학습비 등 교육비 납부 지연",
    }
    results = search_relevant_institutions(query=query, top_k=100, context=context)
    print(f"Query: {query}")
    print(f"Count: {len(results)}")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_test()
