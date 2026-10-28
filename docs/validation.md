# 검증 범위

자동 검증은 실제 계정이나 운영 DB 없이 실행할 수 있다.

- Python unittest: 실제 Wirelog 엔진의 재귀 경로, 정적 관계 추출, 비밀 설정 제외, 브라우저별 계정 분리, API 응답 완료·실패 처리
- JavaScript DOM 테스트: 마크다운 구조, 출처 클릭, 코드 원문 보존, HTML·위험한 링크 차단
- 렌더링 예제: `tests/fixtures/markdown-answers.json`의 합성 답변

```bash
docker compose run --rm web python -m unittest discover -s tests -v
npm ci --ignore-scripts
npm test
```

개발 중 실제 OpenAI API의 응답 완료와 출처 ID를 검증했다. 실제 코드 분석으로 생성된 답변과 소스 스냅샷, 운영 설정은 이 공개 저장소에 포함하지 않는다. 추가 실계정 검증은 사용자가 명시적으로 실행해야 하며 API 사용료가 발생할 수 있다. 생성되는 결과는 기본적으로 Docker 데이터 볼륨에 기록된다.

승인된 웹 OAuth 클라이언트를 사용하는 실제 ChatGPT 로그인, 외부 도메인의 HTTPS 배포, 다중 서버 운영은 별도 통합 검증이 필요하다.
