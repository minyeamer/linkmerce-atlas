# 원격 웹 배포

Docker가 실행되는 서버에 이 프로젝트와 Linkmerce 소스를 배치한다. 사용자 PC에는 Codex CLI가 필요하지 않다. 서버가 소스를 분석하고 각 브라우저의 사용자는 자신의 API 키를 연결한다.

## HTTPS 배포

도메인의 DNS를 서버로 연결하고 80/443 포트를 열어둔다. 기본 Compose는 127.0.0.1:8088에만 바인딩한다. 원격 구성은 Caddy를 앞에 두어 HTTPS 인증서를 발급하고, 공통 접근 비밀번호로 프로젝트 소스 노출을 제한한다. AI 계정은 접근 비밀번호와 별개로 사용자별 브라우저 세션에 연결된다.

```bash
cp .env.example .env
# 비밀번호 해시 생성: 프롬프트에서 비밀번호 입력
docker run --rm -it caddy:2.10.2-alpine caddy hash-password
```

`.env`에 다음을 추가한다. 실제 키나 비밀번호는 Git에 커밋하지 않는다.

```dotenv
DOMAIN=atlas.example.com
PUBLIC_URL=https://atlas.example.com
LINKMERCE_PATH=/srv/linkmerce
APP_USERNAME=team
APP_PASSWORD_HASH='생성한_bcrypt_해시'
ADMIN_TOKEN=임의의_충분히_긴_관리자_토큰
```

```bash
docker compose -f compose.yaml -f compose.remote.yaml up -d --build
```

브라우저에서 `https://atlas.example.com`에 접속하고 공통 접근 계정으로 들어간다. `AI 계정 연결`에서 각 사용자가 자신의 API 키를 입력한다. API 키와 OAuth 토큰은 앱 서버에서 처리하므로, 관리자는 서버·볼륨·백업 접근 권한을 관리해야 한다. 회사의 기존 OIDC/SSO 프록시가 있다면 Caddy의 공통 비밀번호 대신 해당 인증 경계를 사용할 수 있다.

현재 SQLite와 색인은 단일 프로세스·단일 서버 구성을 대상으로 한다. 여러 웹 worker나 서버가 동시에 계정을 갱신하는 구성은 지원하지 않는다. UI 대화 내역은 브라우저 메모리에만 있으며 페이지를 새로 열면 초기화된다.

## ChatGPT 구독 로그인

원격 서비스에서 각 사용자 구독 할당량을 사용하려면 OpenAI의 원격 웹앱용 등록과 구독 사용 권한이 필요하다. API 키 연결 성공은 그 등록을 대신하지 않는다.

승인 후 웹앱의 정확한 이름, 도메인, 콜백 URL을 등록하고 `CHATGPT_CLIENT_ID`, `CHATGPT_CLIENT_SECRET`을 설정한다. 콜백은 `https://atlas.example.com/api/auth/callback`이다. 이어서 다음을 실제 계정으로 검증한다.

1. 로그인에서 표시되는 앱 이름과 구독 사용 동의가 올바른지
2. OIDC 응답 검증과 사용자 세션 분리가 되는지
3. `chatgpt.tokens.use.direct` 권한이 실제로 반환되는지
4. 연결 계정의 모델 목록이 표시되는지
5. 실제 추론이 `response.completed`까지 완료되는지
6. 토큰 갱신·로그아웃 폐기·사용 한도 오류가 올바르게 처리되는지

현재 OAuth 경로는 구현되어 있지만 승인된 클라이언트를 통한 실계정 통합 테스트는 미완료다. 등록 정보가 없으면 로그인 버튼을 비활성화하고 API 키 연결을 사용한다.

## 갱신과 백업

소스 변경 후 UI 왼쪽 아래 갱신 버튼을 누른다. `ADMIN_TOKEN`이 설정되어 있으면 토큰을 입력해야 한다. 소스는 읽기 전용으로 마운트되므로 앱이 원본 Linkmerce 코드를 수정하지 않는다.

`index-data`에는 색인, 암호화된 계정, 암호화 키가 들어간다. 볼륨 전체 백업은 계정 복호화에 필요한 키도 포함하므로 보호된 서버 백업으로 취급한다. 삭제한 계정 정보가 과거 백업에는 남을 수 있다.
