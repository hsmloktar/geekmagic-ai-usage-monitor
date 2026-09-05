# ADR 0001: Python을 초기 구현 언어로 사용

- 상태: 채택
- 날짜: 2026-09-02

## 배경

이 프로젝트는 Windows와 macOS에서 동일하게 실행되어야 하며, 240×240 JPEG 생성,
로컬 네트워크의 multipart HTTP 업로드, 여러 usage provider의 독립적인 조회가 핵심입니다.
초기 버전에는 GUI나 트레이 앱이 없습니다.

## 결정

Python 3.12를 사용하고 uv로 환경을 관리합니다. 이미지 처리는 Pillow, HTTP 처리는
HTTPX를 사용합니다.

## 이유

- 확인된 stock firmware 공개 연동들이 Python/Pillow 기반이라 프로토콜과 이미지 결과를
  비교하기 쉽습니다.
- 240×240 정적 이미지 처리에는 네이티브 UI 프레임워크가 필요하지 않습니다.
- HTTPX의 비동기 API는 이후 Codex/Claude provider를 독립적으로 실행하기에 적합합니다.
- uv를 사용하면 Windows와 macOS에서 동일한 설치 및 실행 명령을 유지할 수 있습니다.

## 고려한 대안: .NET

.NET은 정적 타입, 장기 실행 서비스, self-contained 단일 실행 파일 배포에서 유리합니다.
다만 현재 핵심 위험은 배포가 아니라 장치 프로토콜과 usage 취득 방식의 검증입니다.
SkiaSharp의 플랫폼별 네이티브 자산도 관리해야 하므로 초기 구현 복잡도가 더 큽니다.

다음 조건이 중요해지면 .NET 전환을 다시 검토합니다.

- Python 설치 없이 단일 실행 파일 배포가 필수일 때
- Windows Service 또는 macOS launchd 패키징이 주요 제품 요구사항이 될 때
- 장기간 실행 시 Python 런타임의 메모리/안정성 문제가 측정으로 확인될 때
