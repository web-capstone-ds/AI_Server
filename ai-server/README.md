# DS Vision AI Analysis Server

## 개요
반도체 후공정 비전 검사 장비의 LOT 데이터를 분석하여 RAG(Retrieval-Augmented Generation) 기반 질의응답 및 자동 보고서 생성을 수행하는 Online Area 서버입니다.

## 기술 스택
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Database**: PostgreSQL 16 + pgvector
- **Embedding**: `intfloat/multilingual-e5-small` (384차원, CPU 로컬 실행)
- **LLM**: Anthropic Claude 3.5 Sonnet
- **Scheduler**: APScheduler (일별/주간 보고서)

## 주요 API
- `POST /api/ingest`: Dispatcher로부터 비식별화된 검사 데이터 수신 (API Key 인증)
- `POST /api/query`: RAG 기반 자유 질의응답 (JWT 인증)
- `GET /api/batches`: 웹 백엔드용 KPI 소스 데이터 조회
- `GET /api/report/{type}/latest`: 자동 생성된 최신 보고서 조회

## 시작하기
1. `.env` 파일을 생성하고 필수 환경변수를 설정합니다 (참조: `.env.example`).
2. Docker Compose를 사용하여 서버와 DB를 실행합니다:
   ```bash
   docker-compose up -d
   ```
3. DB 초기 스키마를 적용합니다:
   ```bash
   psql -h localhost -U ai_server -d ai_server -f src/db/schema.sql
   ```

## 로컬 개발
```bash
# 의존성 설치
pip install -e .[dev]

# 서버 실행
uvicorn src.main:app --reload
```
