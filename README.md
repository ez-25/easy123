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
    "학생맞춤통합지원_신청서": {
      "대상학생_정보": {
        "성별": "남",
        "거주지역": "경기도",
        "학교급": "중학교",
        "학년": "3학년"
      },
      "학생_기본사항": {
        "기초수급_보장현황": ["해당없음"],
        "가족현황": ["부모"],
        "학생현황": ["학교폭력 피해 경험"]
      },
      "학생_어려움": {
        "학업": ["성적 급락", "교실 내 불안감"],
        "심리_정서": ["대인기피", "우울/불안", "자해 시도 의혹"],
        "돌봄_안전_건강": ["불면증으로 인한 무기력"],
        "경제_생활": ["해당없음"],
        "기타": "이전 학교에서의 사이버 불링 및 언어 폭력 트라우마로 인해 낯선 사람과의 접촉을 극도로 두려워함."
      },
      "신청_사유": [
        "심각한 대인 공포증으로 인해 모둠 활동 및 급식실 이용 불가",
        "심리적 불안정으로 인한 극단적 선택 언급 등 고위험군 징후 포착"
      ],
      "지원_요청_사항": [
        "위(Wee) 센터 연계 심층 심리 검사 및 외부 상담 기관 연계",
        "정신건강 고위험군 치료비 지원 사업 신청"
      ]
    },
    "관찰일지목록": [
      {
        "직위": "담임",
        "날짜": "2026-05-11",
        "시간": "12:30:00",
        "장소": "상담실",
        "내용": "점심시간에 식사를 거부하고 구석진 자리에서 귀를 막고 있는 모습 발견. 질문에 단답형으로만 응답하며 눈맞춤을 피함.",
        "특이사항": "팔목에 밴드가 붙어 있어 확인하려 했으나 거부함. 우울 척도 검사 결과 '심각' 단계로 나옴."
      }
    ]
  }
}
```

`성명`, `생년월일`, `교사이름`은 받지 않습니다. 나이는 `학교급`과 `학년`으로 추정합니다. 예: `중학교 3학년`은 2026학년도 기준 `2011년생`으로 계산합니다.

### Response 예시

```json
{
  "ai_분석정리_요약": {
    "이름": "익명 학생",
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
- 특징: 학생 `지역`, 학교급/학년 기반 추정 연령, 관찰일지, 신청사유, 지원요청사항, 경제상황, Gemini 도메인 점수를 함께 반영해 적합도 순으로 최대 100건을 반환합니다.
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
