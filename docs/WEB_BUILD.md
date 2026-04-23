# Web Build

## 개발 시 빌드
```bash
cd web
pnpm install
pnpm dev  # 개발 서버 (포트 3000)
```

## 프로덕션 빌드
```bash
cd web
pnpm build  # out/ 디렉토리 생성
# out/ 내용을 Python 서버의 static/ 폴더에 복사
cp -r web/out/* src/piloci/static/
```

## Docker 빌드 (선택)
```bash
docker build -f Dockerfile.web --target export --output type=local,dest=src/piloci/static .
```

## docker-compose.dev.yml 통합

`docker-compose.dev.yml`에서 web 빌드를 Python 서비스 시작 전에 자동 실행하려면 아래처럼 `profiles`를 활용하거나 별도 서비스를 추가합니다.

```yaml
services:
  web-builder:
    build:
      context: .
      dockerfile: Dockerfile.web
      target: builder
    volumes:
      - ./web:/app/web           # 소스 마운트 (개발용)
      - ./src/piloci/static:/app/web/out  # 빌드 결과물 바인드
    command: pnpm build
    profiles:
      - build                    # docker compose --profile build up web-builder

  piloci:
    # ... 기존 Python 서비스 설정
    depends_on:
      web-builder:
        condition: service_completed_successfully
```

개발 중 핫리로드가 필요하면 `pnpm dev`를 직접 실행하고 Next.js 포트(3000)에서 확인하세요.
Python FastAPI 서버(포트 8000)로의 API 요청은 `next.config.ts`의 `rewrites` 또는 프록시 설정으로 전달합니다.
