# 제3자 소프트웨어

루트 `LICENSE`의 MIT 라이선스는 이 프로젝트의 자체 코드에 적용한다. 의존성과 함께 배포하는 코드는 각 프로젝트의 라이선스를 따른다.

| 구성요소 | 라이선스 | 배포 방식 |
| --- | --- | --- |
| Wirelog | LGPL-3.0-or-later | Docker에서 고정 revision을 빌드한 공유 라이브러리. 해당 소스와 라이선스는 이미지의 `/opt/wirelog-src`에 포함 |
| markdown-it | MIT | `app/static/vendor/markdown-it.min.js`와 인접 라이선스 파일 |
| DOMPurify | Apache-2.0 또는 MPL-2.0 | `app/static/vendor/purify.min.js`와 인접 라이선스 파일 |

Wirelog 빌드에 포함되는 하위 의존성의 소스와 라이선스도 이미지의 소스 디렉터리에서 확인할 수 있다. Python·Node.js 패키지의 버전은 `requirements.txt`, `package.json`, `package-lock.json`에 기록하며 해당 패키지의 라이선스를 유지한다.
