# 학생 맞춤형 지원 기관 추천 API (Step 1-4)

FastAPI 기반 기본 서버 세팅과 데이터 수신 엔드포인트를 포함합니다.

## 1) 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2) 환경 변수 설정

```bash
copy .env.example .env
```

필요 시 `.env` 값을 수정하세요.

## 3) 서버 실행

```bash
uvicorn app.main:app --reload
```

기본 주소: `http://127.0.0.1:8000`
Swagger 문서: `http://127.0.0.1:8000/docs`

## 4) API 테스트

### 엔드포인트

- `POST /api/analyze-student`

### Request Body (요청 스키마 확정)

```json
{
  "전체데이터": {
    "통합신청서정보": {
      "학생인적사항": {
        "학생이름": "홍길동",
        "지역": "대구광역시",
        "학년": 3,
        "반": 1,
        "생년월일": "2015-05-20",
        "성별": "남"
      },
      "가정환경및자격": {
        "학생기본사항": "부모님과 동거 중",
        "기초수급보장현황": "차상위계층",
        "가족현황": "부, 모, 여동생"
      },
      "학생상태": {
        "학생현황": "교우관계 원만하나 수업 집중력 부족",
        "학생어려움": {
          "학업": "기초 학력 미달 및 수업 참여 저조",
          "심리_정서": "감정 조절에 어려움을 겪으며 불안 증세 보임",
          "돌봄_안전_건강": "방과 후 보호자 부재로 인한 돌봄 공백",
          "경제_생활": "체험학습비 등 교육비 납부 지연",
          "기타": "특이사항 없음"
        }
      },
      "신청사유": "교내 다수 교사의 관찰 결과 공통적으로 정서적 불안 및 돌발 행동이 포착되어 통합 지원 신청함",
      "지원요청사항": "전문 상담 및 방과 후 학습 지원 연계"
    },
    "관찰일지목록": [
      {
        "교사이름": "김철수",
        "직위": "담임",
        "날짜": "2026-04-07",
        "시간": "09:10:00",
        "장소": "교실",
        "내용": "1교시 수업 시작 전, 가방을 던지며 자리에 앉지 않고 교실 뒤편을 배회함. 진정시키려 했으나 거부함.",
        "특이사항": "등교 직후부터 기분이 매우 저조해 보임."
      }
    ]
  }
}
```

### Response 예시

```json
{
  "ai_분석정리_요약": {
    "이름": "홍길동",
    "요약분석": "학생은 정서적 불안과 돌봄 공백이 동시에 관찰되며 학업 결손 신호가 지속되고 있습니다. 상담 및 정서 안정 지원과 함께 방과 후 돌봄 연계, 기초학력 보강이 병행되어야 합니다.",
    "핵심신호": ["정서 안정 지원 필요", "돌봄 공백", "기초 학력 미달"]
  },
  "ai_추천기관_제도": [
    {
      "category": "기관",
      "suitability": 92,
      "welfareType": "지역센터",
      "servId": "ORG0005",
      "servNm": "대구청소년성문화센터",
      "region": "대구광역시 달서구",
      "agency": "대구광역시 달서구",
      "department": "",
      "intrsThemaArray": ["청소년"],
      "lifeArray": ["청소년"],
      "srvPvsnNm": "상담/지원",
      "sprtCycNm": "수시",
      "servDgst": "대구광역시 달서구 앞산순환로 180",
      "servDtlLink": "http://www.dgsay.net",
      "inqNum": 0,
      "contact": "053-653-7755",
      "sourceDataset": "integrated_institution_data.csv"
    }
  ]
}
```

## 5) RAG 검색

### 데이터 소스

- `integrated_institution_data.csv`
- `transformed_scholarships_detailed_dgst.csv`
- `welfare_integrated_data.csv`

### 검색 함수

- 구현 파일: `app/rag.py`
- 함수: `search_relevant_institutions(query, top_k=100, csv_path=None, context=None)`
- 방식: 기본은 로컬 재랭킹 기반 검색이며, `USE_GEMINI_EMBEDDINGS=true`일 때 Gemini Embedding + FAISS를 함께 사용합니다.
- 특징: 학생 `지역`, `생년월일`, 관찰일지, 신청사유, 지원요청사항, 경제상황, Gemini 도메인 점수를 함께 반영해 적합도 순으로 최대 100건을 반환합니다.
- 지역/연령 불일치 항목은 감점이 아니라 후보 단계에서 제외합니다. 따라서 조건에 맞는 제도만 남으면 100개보다 적게 반환될 수 있습니다.

### 단독 테스트

```bash
python test_rag_search.py
```

기본 모드(`USE_GEMINI_EMBEDDINGS=false`)에서는 Gemini Embedding 없이도 테스트할 수 있습니다.
`GEMINI_API_KEY`가 없어도 로컬 요약/관찰일지 분석 fallback으로 API가 동작합니다.

## 6) Gemini 분석 연동 (Step 3)

- 구현 파일: `app/gemini_analyzer.py`
- 함수: `analyze_student_data(request_data)`
- 모델: `.env`의 `GEMINI_MODEL` (기본 `gemini-1.5-flash`)
- `POST /api/analyze-student` 호출 시 Gemini 분석 결과가 `ai_analysis`에 포함되어 반환됩니다.

## 7) 최종 조합 응답 (Step 4)

- 흐름: 요청 수신 -> Gemini 분석(`핵심신호`) -> 다중 CSV RAG 검색(top 100) -> 최종 JSON 조립
- 예외 처리:
  - Gemini 호출 실패: `502`
  - 핵심신호 비어있음: `422`
  - RAG 검색 실패: `500`
