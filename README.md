# LandUP — 팝업스토어 공간 자동 배치 시스템

LLM (Claude API) + LangGraph 기반 5~50평 팝업스토어 공간의 가구 좌표 + 동선 자동 결정 서비스.

본 repo 는 **roach-hue (jinkyu) 포트폴리오용 사본**입니다.
원본 팀 repo = [WeAre2Jo/Project_Landup](https://github.com/WeAre2Jo/Project_Landup) (private).

---

## 팀 구성 (5인) + 본인 담당

| 영역 | 담당 |
|---|---|
| **★ 배치 엔진 본체 + LLM 인프라 + 도메인 룰 (nodes_small/)** | **jinkyu (본 repo 작성자)** |
| 대형 공간 배치 (nodes_large/) | shin |
| DB / 인프라 / CI-CD / 배포 | shin |
| 회원/인증/결제 | 인홍 / 희영 / 연화 |
| 프론트엔드 UI | 5인 분담 |

**본인 작업 분량**: 35일 / 191 commit / 단독 담당.

---

## 본인 기여 (핵심 4 묶음)

### 1. 자동 배치 엔진 본체

도면 입력 → 배치 가능 영역 계산 → 가구 후보 선별 → 좌표 결정 → 검증 → 동선 → 출력.
`backend/python/app/nodes_small/` 디렉토리 전담.

### 2. LLM 호출 인프라 표준화 + 2단계 Reviewer + 수렴 조건

- 모든 LLM 호출을 1개 함수로 통일 (응답 검증 / 재시도 / 비용 추적 자동)
- **2단계 LLM Reviewer**: 1단계 = "의도가 잘못됐나" (배치 전) / 2단계 = "결과가 잘못됐나" (배치 후)
- 좌표·거리 같은 결정론적 영역은 코드 / zone 의미·동선 적정성은 LLM 분담
- **무한 루프 차단** = 조건부 2회 시도 + 95% 일치 시 조기 종료

### 3. 도메인 룰 시스템 (VMD 35 룰, 하이브리드)

실무 인테리어 규칙 (Visual Merchandising) 을 35 룰로 체계화.

- 가벽 자동 배치 / 입구 정면 차단 / 가벽 짝꿍 (사진월 등) 강제 매칭
- 화장실·계단·기둥·분전반 통합 금지 영역
- 스프링클러 천장 높이 기반 동적 차단
- clearance 3단계 우선순위 (매뉴얼 → 면적 → 기본값)
- 단순 if/else 가 아닌 **하이브리드 (코드 + LLM 자연어 판단)**

### 4. 풀스택 분리 + 외부 시스템 연동

- Python 단일 서버 → Spring Boot Java + Python 분리 (서비스 분리 구조 제안)
- 일반 API = Java / LLM 처리 = Python
- 레퍼런스 이미지 자동 수집 (DuckDuckGo) + Vision LLM 부적절 판정 → sha256 블랙리스트 등록 → 다음 수집 시 URL 무관 자동 차단 (Python ↔ Java 연동)

---

## 설계 판단 강조

| # | 항목 | 의미 |
|---|---|---|
| 1 | **파서 어댑터 패턴** | DXF / PDF / JPG / DWG 다양한 입력 → 표준 polygon 출력으로 변환. 새 형식 추가 시 어댑터 1개만. 호출자는 입력 형식 모름 |
| 2 | **SSOT (Single Source of Truth)** | 카테고리 정의가 5곳에 흩어져 있던 것을 `categories.py` 1곳으로 통합. 신규 카테고리 추가 = 1곳만 수정. drift (불일치) 구조적 차단 |
| 3 | **상수 중앙화** | 매직 넘버 (50 / 450 / 1500) 제거 → 이름 있는 상수로 (`vmd_constants`). 의미 명시 + 변경 시 한 곳만 |
| 4 | **★ sub-graph 선택적 적용** | LangGraph 가 강력하나 모든 흐름에 도배하면 추상화 비용 증가. 직렬 처리로 충분한 부분 (파싱·영역 계산·가구 선별) 은 코드, **의사결정 분기 / 충돌 / 양보가 발생하는 배치 시점부터만 graph 도입**. 추상화 비용 최소화 + 자율 분기 가치 극대화 |

---

## 시연 실행 (Python 직통 모드 — 권장)

**Java / Redis / Worker / MySQL 다 안 띄움**. Python 백엔드 + Vite dev server 2개만 띄워서 자동 배치 흐름만 시연.

### 사전 준비

1. `backend/.env` 생성:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   ([console.anthropic.com](https://console.anthropic.com/) 에서 발급)

2. `frontend/.env.local` 생성:
   ```
   VITE_USE_DIRECT=true
   VITE_DIRECT_URL=http://localhost:8000
   ```

### 실행

```bash
# 터미널 1 — Python 백엔드
cd backend/python
pip install -r requirements.txt
uvicorn app.api:app --port 8000

# 터미널 2 — 프론트엔드
cd frontend
npm install
npm run dev
```

브라우저: `http://localhost:5173`

### 시연에서 보여줄 수 있는 것

- ✅ 자동 배치 엔진 핵심 (도면 → 배치 결과)
- ✅ 레퍼런스 이미지 DDG 수집 + Vision 분석
- ✅ 2단계 Reviewer + 수렴 조건
- ✅ VMD 룰 + 가벽 자동 배치

### 시연에서 보여줄 수 없는 것 (운영 환경에서만 작동)

- 회원가입 / OAuth 로그인 (네이버 / 카카오 / 구글)
- 결제 (토스페이먼츠)
- sha256 블랙리스트 자동 차단 (Java backend 필요)
- 관리자 페이지 / 분석 보고서 영구 저장

---

## 운영 환경 (전체 서비스)

OAuth / 결제 / 블랙리스트 / 관리자 페이지까지 동작시키려면 `.env.example` 의 전체 환경변수 채우고 `docker compose` 로 Java + Redis + MySQL 까지 띄워야 합니다.

자세한 환경변수 매트릭스는 [.env.example](.env.example) 참고.

---

## 아키텍처 (요약)

```
[Frontend (React + Vite)]
        │
        ├── 시연 모드: Python 직통 (Anthropic API key 1개로 동작)
        │
        └── 운영 모드: Java 경유
                │
        [Java Backend (Spring Boot)]
        │   ├── 회원/인증/결제 (OAuth + JWT + Toss)
        │   ├── 관리자 페이지 + 분석 보고서 영속화
        │   └── sha256 블랙리스트 (이미지 부적절 자동 차단)
                │
                ▼
        [Python Backend (FastAPI + LangGraph)]  ← 본인 담당 영역
            ├── DXF / PDF / JPG 파서 (어댑터 패턴)
            ├── 배치 영역 계산 (Shapely / NetworkX)
            ├── 가구 후보 선별 + 좌표 결정
            ├── 2단계 LLM Reviewer (95% 수렴 + 2회 시도)
            ├── VMD 35 룰 + 가벽 자동 배치
            └── 레퍼런스 이미지 자동 수집 (DDG + Vision)
```

---

## 라이선스

본 repo 는 팀 프로젝트의 포트폴리오용 사본이며, 상업적 이용은 불가합니다. 코드 열람 및 기술 평가 목적에 한해 공개됩니다.
