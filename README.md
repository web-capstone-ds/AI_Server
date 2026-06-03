# DS Vision AI Server

반도체 후공정 비전 검사 장비의 LOT 데이터를 분석하는 Online Area AI 분석 서버.  
Dispatcher로부터 비식별화된 검사 데이터를 수신하고, RAG(Retrieval-Augmented Generation) 기반 질의응답 및 자동 보고서를 생성합니다.

## 기술 스택

| 항목 | 내용 |
|---|---|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Database | PostgreSQL 16 + pgvector |
| Embedding | `intfloat/multilingual-e5-small` (384차원, CPU) |
| LLM | Claude Sonnet 4.6 (`claude-sonnet-4-6`) |
| Scheduler | APScheduler |
| Migration | Alembic |

## 디렉토리 구조

```
AI_Server/ai-server/
├── src/
│   ├── api/          # HTTP 엔드포인트 (ingest, query, batches, report, health)
│   ├── db/           # DB 풀 및 쿼리 (pgvector, 임베딩, 보고서)
│   ├── llm/          # Claude 클라이언트 및 보고서 생성기
│   ├── models/       # Pydantic 데이터 모델
│   ├── pipeline/     # 데이터 전처리, 청킹, 임베딩, 잡 워커
│   ├── rag/          # RAG 검색기, 리랭커, 컨텍스트 빌더
│   ├── scheduler/    # 일별/주간 자동 보고서 스케줄러
│   └── utils/        # 인증, 로깅, JWT 유틸
├── alembic/          # DB 마이그레이션
└── tests/            # 단위/통합/E2E 테스트
```

## 주요 API

| 메서드 | 경로 | 설명 | 인증 |
|---|---|---|---|
| POST | `/api/ingest` | Dispatcher로부터 검사 데이터 수신 | API Key |
| POST | `/api/query` | RAG 기반 자유 질의응답 | JWT |
| GET | `/api/batches` | KPI 소스 데이터 조회 | JWT |
| GET | `/api/report/{type}/latest` | 최신 자동 보고서 조회 | JWT |
| GET | `/health` | 헬스체크 | 없음 |

## 실행 방법

```bash
# 1. 환경변수 설정
cp ai-server/.env.example ai-server/.env
# ANTHROPIC_API_KEY, AI_INGEST_API_KEY 등 필수값 입력

# 2. Docker Compose로 서버 + DB 실행
cd ai-server
docker compose up -d

# 3. DB 마이그레이션
alembic upgrade head
```

로컬 개발 시:
```bash
cd ai-server
pip install -e .[dev]
docker compose up pgvector -d
alembic upgrade head
uvicorn src.main:app --reload
```

## 포트

| 서비스 | 포트 |
|---|---|
| AI Server (FastAPI) | 8000 |
| pgvector (PostgreSQL) | 5433 |
