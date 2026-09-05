# GeekMagic AI Usage Monitor

GeekMagic SmallTV Ultra의 순정 펌웨어를 유지하면서 Windows와 macOS에서 생성한
240×240 AI 사용량 대시보드를 로컬 네트워크로 전송하는 프로젝트입니다.

현재 상태는 **Phase 7 구현**입니다. 현재 컴퓨터에 로그인된 Codex 및 Claude 계정의
5시간/주간 사용량을 읽고, 240×240 대시보드로 렌더링해 GeekMagic으로 60초마다
전송합니다. Windows 장기 실행을 위한 중복 실행 방지, 회전 파일 로그, 안정적인 실행
스크립트와 종료 처리에 더해, 창 없는 알림 영역 앱과 바탕화면 바로가기를 제공합니다.
macOS 관련 작업은 별도 후순위 단계로 진행합니다.

## 기술 선택

- Python 3.12: Windows와 macOS에서 동일한 코드로 실행할 수 있고, 로컬 HTTP 및 이미지
  처리 도구가 성숙해 있습니다.
- uv: 가상환경, 의존성, 잠금 파일을 한 도구로 관리합니다.
- Pillow: 240×240 JPEG 렌더링에 충분하며, 공개 GeekMagic 연동 사례와 동일한 계열의
  렌더링 도구라 결과를 비교하기 쉽습니다.
- HTTPX: multipart 업로드와 비동기 HTTP 요청을 지원해 이후 provider 병렬 조회와
  업데이트 루프에 재사용할 수 있습니다.
- pytest, Ruff, mypy: 테스트, 린트/포맷, 정적 타입 검사를 담당합니다.

Python을 .NET보다 우선한 이유와 재검토 조건은
[`docs/decisions/0001-use-python.md`](docs/decisions/0001-use-python.md)에 기록했습니다.

## 디렉터리 구조

```text
src/geekmagic_ai_monitor/
├─ configuration/   # appsettings 로딩 및 검증
├─ geekmagic/       # 순정 펌웨어 HTTP 통신
├─ rendering/       # 240×240 이미지 렌더링
├─ runtime/         # update loop
└─ usage/
   ├─ models/       # 공통 usage 모델
   └─ providers/    # Codex 등 provider별 usage 조회
tests/              # 자동화 테스트
```

Phase 7에서는 provider 공통 protocol, 장기 실행 `UpdateService`, Windows 운영 지원과
알림 영역 UI까지 구현되어 있습니다.

## 개발 환경 준비

Python 3.12와 [uv](https://docs.astral.sh/uv/)가 필요합니다.
실사용량을 조회하려면 각 Windows/macOS 컴퓨터에 Codex CLI와 Claude Code가 설치되어
있고 해당 컴퓨터에서 각각 계정 로그인이 완료되어 있어야 합니다. Claude Code 2.1.258에서
실제 동작을 확인했습니다.

```powershell
# Windows Codex CLI 설치 및 확인
npm install --global @openai/codex@latest
where.exe codex
codex --version

uv sync
uv run ruff check .
uv run mypy
uv run pytest
```

Windows 바탕화면 실행 스크립트는 실행할 때 레지스트리에 저장된 최신 사용자 PATH를
다시 읽습니다. 따라서 npm 전역 경로를 사용자 PATH에 등록한 뒤에는 Windows에서
로그아웃하지 않아도 새로 설치한 `codex` 명령을 사용할 수 있습니다.

macOS에서도 같은 명령을 사용합니다.

## 설정

기본 설정은 `appsettings.json`에 있습니다. 실제 장치 주소는 Git에서 제외되는
`appsettings.local.json`에 같은 구조로 작성합니다. 로컬 설정은 기본 설정을 덮어씁니다.

```json
{
  "GeekMagic": {
    "Host": "192.168.0.100"
  },
  "Codex": {
    "Executable": "codex",
    "RequestTimeoutSeconds": 15
  },
  "Claude": {
    "Executable": "claude",
    "RequestTimeoutSeconds": 20
  },
  "UpdateIntervalSeconds": 60
}
```

저장소의 기본 `Host`는 비워 두었습니다. 현재 PC의 실제 IP는 `appsettings.local.json`에만
저장됩니다.

## 명령

모든 명령은 프로젝트 루트에서 실행합니다.

```powershell
# 읽기 전용: 펌웨어 모델과 버전 확인
uv run geekmagic-ai-monitor probe

# 네트워크를 사용하지 않고 artifacts/에 240×240 JPEG 생성
uv run geekmagic-ai-monitor render-test

# probe가 stock Ultra로 확인된 경우에만 이미지 생성, 업로드, 표시
uv run geekmagic-ai-monitor push-test

# 임시 사용량으로 최종 대시보드 생성
uv run geekmagic-ai-monitor render-dashboard-test

# 임시 사용량 대시보드를 실제 기기에 전송
uv run geekmagic-ai-monitor push-dashboard-test

# 로그인된 Codex 계정의 현재 사용량만 읽어서 출력
uv run geekmagic-ai-monitor codex-usage

# 실제 Codex 사용량으로 로컬 대시보드 생성(Claude는 Unavailable)
uv run geekmagic-ai-monitor render-codex-usage

# 실제 Codex 사용량 대시보드를 기기에 전송
uv run geekmagic-ai-monitor push-codex-usage

# 로그인된 Claude 계정의 현재 사용량만 읽어서 출력
uv run geekmagic-ai-monitor claude-usage

# Codex와 Claude 실사용량으로 전체 대시보드 생성
uv run geekmagic-ai-monitor render-live-usage

# Codex와 Claude 실사용량 대시보드를 기기에 전송
uv run geekmagic-ai-monitor push-live-usage

# 전체 pipeline을 한 번 실행
uv run geekmagic-ai-monitor run-once

# 전체 pipeline을 설정된 간격으로 계속 실행(Ctrl+C로 종료)
uv run geekmagic-ai-monitor run

# Windows 권장 실행: 현재 작업 디렉터리와 무관하게 한 번 실행
powershell -ExecutionPolicy Bypass -File .\windows\run-monitor.ps1 -Once

# Windows 권장 실행: 현재 작업 디렉터리와 무관하게 계속 실행
powershell -ExecutionPolicy Bypass -File .\windows\run-monitor.ps1

# 창 없는 알림 영역 앱의 바탕화면 바로가기 설치
powershell -ExecutionPolicy Bypass -File .\windows\install-desktop-shortcut.ps1

# 바탕화면 바로가기 제거(실행 중인 앱은 종료하지 않음)
powershell -ExecutionPolicy Bypass -File .\windows\uninstall-desktop-shortcut.ps1
```

이미지를 만드는 명령의 출력 경로를 바꾸려면 명령 뒤에 `--output <path>`를 지정합니다.
`push-test`는 안전을 위해 다음 조건을 모두 검사합니다.

- `/v.json` 또는 stock Ultra 호환 endpoint로 순정 Ultra 확인
- 파일명이 경로를 포함하지 않는 `.jpg` 또는 `.jpeg`
- 이미지가 JPEG 데이터인지 확인
- HTTP 오류나 펌웨어의 `FAIL` 응답을 성공으로 처리하지 않음

## 확인된 SmallTV Ultra 순정 펌웨어 프로토콜

공개 구현의 실제 전송 코드를 기준으로 다음 흐름을 확인했습니다.

1. `GET /v.json`을 우선 조회하고, 사용할 수 없으면 `GET /app.json`으로 stock Ultra를 확인
2. 240×240 JPEG를 multipart 필드 `file`로 `POST /doUpload?dir=/image/`에 업로드
3. `GET /set?theme=3`으로 Photo Album 테마 선택
4. `GET /set?img=/image/{filename}`으로 업로드한 이미지를 선택

근거:

- [geekmagic-hacs stock firmware profile](https://github.com/adrienbrault/geekmagic-hacs/blob/main/custom_components/geekmagic/profiles.py)
- [geekmagic-hacs HTTP transport](https://github.com/adrienbrault/geekmagic-hacs/blob/main/custom_components/geekmagic/transport.py)
- [GeekMagic AI Status protocol summary](https://github.com/MacheteFlow/GeekMagic-AI-Status#the-original-firmware-is-never-touched)
- [GeekMagic 공식 SmallTV Ultra 저장소](https://github.com/GeekMagicClock/smalltv-ultra)

같은 이름으로 판매되는 기기에 서로 다른 펌웨어가 존재할 수 있으므로, 쓰기 전에 읽기
전용 probe를 수행하고 stock Ultra가 확인되지 않으면 전송을 중단합니다.

## 실기 검증

2026-09-02에 실제 SmallTV Ultra에서 Phase 1 흐름을 확인했습니다.

- `/v.json`: `SmallTV-Ultra`, `Ultra-V9.0.51`
- `POST /doUpload?dir=/image/`: `geekmagic-ai-monitor.jpg` 업로드 성공
- `/set?theme=3` 및 `/set?img=/image/geekmagic-ai-monitor.jpg`: 성공
- 후속 `/app.json`: `theme`이 `3`으로 변경됨
- 후속 `/filelist?dir=/image/`: 업로드한 14 KB JPEG 확인
- `/album.json`: `autoplay`가 `0`이어서 선택한 테스트 이미지가 고정됨

장치의 물리 화면에 테스트 카드가 정상 표시되는 것을 사용자가 확인했습니다.

## Phase 2 임시 데이터

`DashboardRenderer`는 `AiUsageSnapshot`만 입력받으며 API 호출이나 장치 통신을 하지
않습니다. 현재 CLI 샘플은 다음 사용한 비율(`UsedPercent`)을 사용합니다.

- Codex: 5시간 72%, 주간 43%
- Claude: 5시간 61%, 주간 37%

값이 없는 사용량 행은 빈 게이지와 `None`으로 표시하며 전체 렌더링을 계속합니다.

샘플 대시보드는 실제 `Ultra-V9.0.51` 기기에 업로드했으며, 후속 조회에서 `theme=3`과
15 KB `geekmagic-ai-monitor.jpg` 파일을 확인했습니다. 물리 화면의 가독성도 사용자가
확인했습니다.

## Phase 3 Codex 사용량

Codex 사용량은 공식 [Codex app-server](https://learn.chatgpt.com/docs/app-server)의
JSON-RPC 호환 `account/rateLimits/read` 요청으로 조회합니다. 응답의
`rateLimitsByLimitId.codex`를 우선 사용하고, 이전 형식인 `rateLimits`도 지원합니다.
`windowDurationMins`가 300인 창을 5시간, 10080인 창을 주간 사용량으로 매핑합니다.
어느 한 창만 전달된 경우에는 존재하는 값만 사용하며, 누락된 행은 빈 게이지와 `None`으로
표시합니다.

provider는 매 조회 시 `codex app-server` 하위 프로세스를 직접 실행하고 표준 입출력으로만
통신합니다. 프로젝트가 Codex 인증 파일이나 토큰을 읽거나 복사하거나 저장하지 않으며,
현재 컴퓨터의 Codex CLI 로그인 상태를 그대로 사용합니다. 실행 파일 이름과 요청 제한
시간은 `appsettings.json`의 `Codex` 섹션에서 변경할 수 있습니다.

2026-09-02 Windows 실기에서는 npm으로 설치한 `codex-cli 0.152.1`을 바탕화면 바로가기
환경에서 찾아 사용량을 조회하고 로컬 네트워크의 GeekMagic 기기에 전송하는 흐름을
확인했습니다.

한 provider가 실패해도 이후 통합 단계에서 다른 provider와 렌더러가 독립적으로 동작할 수
있도록 `UsageProvider` protocol과 공통 `UsageInfo` 사이에서 변환합니다. Phase 3 전용
명령에서는 Claude 영역을 빈 게이지와 `None`으로 표시하고, Phase 4의 `*-live-usage`
명령에서는 두 provider를 병렬 조회합니다. 어느 한쪽이 실패해도 다른 provider는 유지됩니다.

## Phase 4 Claude 사용량

Claude 사용량은 공식 [Claude Code `/usage` 명령](https://code.claude.com/docs/en/commands)을
비대화형 JSON 모드로 실행해 조회합니다. `/usage` 결과의 `Current session`을 5시간,
`Current week`를 주간 사용량으로 변환하며 reset 시간도 함께 읽습니다. IANA 시간대를
Windows와 macOS에서 동일하게 처리하기 위해 Python `tzdata`를 사용합니다.

실행 시 도구와 세션 저장을 비활성화하고 매우 작은 최대 비용을 지정합니다. 또한 반환된
JSON에서 비용과 입력·출력·캐시 토큰이 모두 0인지 확인하며, 하나라도 0이 아니면 결과를
거부합니다. 실제 Claude Code 2.1.258에서 0토큰·0비용 동작을 확인했습니다. 프로젝트는
Claude credential 파일이나 OAuth token을 읽거나 저장하지 않습니다.

공식 상태줄에도 같은 5시간/7일 `used_percentage`와 Unix reset 시간이 제공됩니다. 해당
스키마는 [Claude Code status line 문서](https://code.claude.com/docs/en/statusline)에서 확인할
수 있습니다. provider는 상태줄이 활성 세션에서만 갱신되는 제약을 피하기 위해 `/usage`를
사용합니다.

Claude가 구독 사용 중임을 확인할 수 있지만 정량 한도 행을 생략하고 사용 패턴 분석만
반환하는 경우도 정상적인 부분 데이터로 처리합니다. 이때 누락된 5시간 또는 주간 행은 빈
게이지와 `None`으로 표시하며, 전혀 관련 없는 출력은 계속 오류로 거부합니다.

2026-09-02에 Codex와 Claude 실사용량을 병렬 조회한 전체 대시보드를 실제
`SmallTV-Ultra / Ultra-V9.0.51`에 전송했습니다. 전송 시점 값은 Codex 5시간 26%·주간
31%, Claude 5시간 12%·주간 8%였으며, 후속 조회에서 `theme=3`과 14 KB JPEG를
확인했습니다.

## Phase 5 자동 업데이트

`UpdateService`는 시작 직후 첫 업데이트를 실행한 다음 `UpdateIntervalSeconds` 간격으로
다음 작업을 반복합니다.

1. Codex와 Claude provider 병렬 조회
2. 한 provider나 개별 한도 값이 없으면 해당 행을 빈 게이지와 `None`으로 대체
3. `AiUsageSnapshot` 생성 및 240×240 JPEG 렌더링
4. 순정 Ultra probe 후 이미지 업로드 및 선택
5. 기기나 파일 작업이 실패하면 Console에 기록하고 다음 주기에서 재시도

주기는 이전 주기의 시작 시점을 기준으로 계산하며 서로 겹치지 않습니다. 한 주기가 설정
간격보다 오래 걸리면 다음 주기를 즉시 시작합니다. `Ctrl+C`로 프로그램을 종료해도 기기에
별도의 초기화 요청을 보내지 않으므로 마지막으로 전송한 화면이 그대로 유지됩니다.

2026-09-02 Windows 실기에서 22:23:17과 22:24:17에 두 주기가 정확히 60초 간격으로
시작되고 모두 기기 전송에 성공하는 것을 확인했습니다. 두 번째 화면은 Codex 5시간
36%·주간 33%, Claude 5시간 12%·주간 8%, `Updated 22:24`, `WIN`으로 표시됐습니다.

## Phase 6 Windows 운영 안정화

Windows에서는 `windows/run-monitor.ps1`을 권장 진입점으로 사용합니다. 스크립트가 자신의
위치를 기준으로 프로젝트 루트, 설정, 출력, 로그와 잠금 경로를 절대 경로로 계산하므로
다른 작업 디렉터리나 작업 스케줄러에서 실행해도 동일하게 동작합니다.

- 현재 이미지: `artifacts/geekmagic-current.jpg`
- 운영 로그: `artifacts/logs/monitor.log` (시작할 때 오늘 날짜 기록만 유지)
- 로그 보관: 파일당 1 MB, 백업 5개
- 실행 잠금: `artifacts/geekmagic-monitor.lock`
- `-Once`: 전체 pipeline을 한 번만 실행
- 인자 없음: 60초 update loop 실행

OS 수준 파일 잠금을 사용하므로 이미 모니터가 실행 중이면 두 번째 `run` 또는 `run-once`는
즉시 오류로 종료됩니다. 비정상 종료나 `Ctrl+C` 이후에는 OS가 잠금을 해제하므로 별도의
잠금 파일 정리가 필요하지 않습니다. `Ctrl+C`로 종료할 때 실행 중인 provider 하위
프로세스와 HTTP client도 정리하며, GeekMagic에는 마지막 화면을 그대로 남깁니다.

2026-09-02 Windows에서 다음 운영 시나리오를 실제로 확인했습니다.

- 프로젝트 밖 `C:\Users\<USERNAME>`에서 `run-monitor.ps1 -Once` 실행 및 기기 전송 성공
- 실행 중 두 번째 인스턴스가 `already running`으로 차단됨
- `Ctrl+C` 종료 로그 기록 및 잠금 해제 확인
- 종료 직후 `run-monitor.ps1 -Once` 재실행 성공
- 로그 파일 생성 및 자동 회전 테스트 통과
- provider 장애 격리와 기기 장애 다음 주기 재시도 테스트 통과

## Phase 7 Windows 알림 영역 앱

Windows 로그인 자동 실행은 사용하지 않습니다. 바탕화면의 `GeekMagic AI Monitor` 바로가기를
더블클릭하면 PowerShell 창 없이 모니터가 시작되고, 작업 표시줄 오른쪽 알림 영역에 청록색과
주황색 막대 아이콘이 표시됩니다. 이미 실행 중일 때 바로가기를 다시 눌러도 중복 프로세스는
생성되지 않습니다.

아이콘을 왼쪽 클릭하면 현재 상태 알림을 표시하고, 오른쪽 클릭하면 다음 메뉴를 제공합니다.

- `상태`: 시작 중, 업데이트 중, 정상 및 마지막 업데이트 시각, 재시도 상태
- `지금 갱신`: 현재 갱신 중이면 완료 직후, 대기 중이면 즉시 한 번 갱신
- `갱신 주기`: `1분`, `5분`, `10분` 중 하나를 선택하고 현재 값에 체크 표시
- `로그 열기`: `artifacts/logs/monitor.log`를 메모장으로 열기
- `종료`: update loop와 실행 중인 provider를 정리하고 알림 영역 앱 종료

선택한 갱신 주기는 `artifacts/tray-settings.json`에 저장되어 앱을 다시 실행해도 유지됩니다.
주기를 변경하면 현재 대기가 즉시 새 간격으로 재계산됩니다. 이 트레이 전용 선택은 명령행
`run`에서 사용하는 `appsettings.json`의 `UpdateIntervalSeconds` 값을 변경하지 않습니다.

바로가기는 Windows 시스템 PowerShell을 `-WindowStyle Hidden`으로 실행하며 프로젝트의
`windows/start-tray.ps1`을 호출합니다. 실행 스크립트는 숨김 트레이 프로세스를 분리한 뒤
즉시 종료하므로 PowerShell 창이나 작업 표시줄 항목이 남지 않습니다. 따라서 Codex 내부
런타임이나 현재 작업 디렉터리에 의존하지 않습니다. 트레이 UI는 공식적으로 Windows 메뉴와 종료를 지원하는
[pystray](https://pystray.readthedocs.io/en/latest/usage.html)를 사용합니다.

2026-09-02 Windows 실기에서 다음을 확인했습니다.

- 창 없는 알림 영역 프로세스와 아이콘 시작
- 시작 직후 Codex/Claude 조회 및 GeekMagic 전송 성공
- `C:\Users\<USERNAME>\Desktop\GeekMagic AI Monitor.lnk` 생성
- 바로가기 대상이 Windows 시스템 PowerShell이고 숨김 실행 인자를 사용하는지 확인
- 바로가기 재실행 후 PowerShell 프로세스와 작업 표시줄 항목이 남지 않는지 확인
- 실행 잠금과 운영 로그 생성 확인
- 알림 영역 `종료` 메뉴로 아이콘과 프로세스가 종료되는지 확인

## 단계별 범위

- Phase 1: 장치 probe, 테스트 JPEG 생성, 최소 업로드/표시 명령 — 완료
- Phase 2: 임시 데이터를 사용하는 최종 대시보드 렌더러 — 완료 및 실기 확인
- Phase 3: Codex usage provider — 완료 및 실기 확인
- Phase 4: Claude usage provider — 완료 및 실기 확인
- Phase 5: 60초 update loop — 구현 및 Windows 실기 확인
- Phase 6: Windows 운영 안정화 및 최종 검증 — 완료
- Phase 7: Windows 알림 영역 실행 및 바탕화면 바로가기 — 완료 및 실기 확인
- Phase 8: macOS 실행·실기 검증 — 후순위
- Phase 9: macOS 실행 방식 결정 — 후순위

## Windows 우선 마무리 순서

### Phase 6 — Windows 운영 안정화 — 완료

1. 중복 실행 방지
2. 백그라운드 실행에서도 확인할 수 있는 파일 로그와 보관 정책
3. 프로젝트 디렉터리가 아닌 위치에서 실행해도 설정과 출력 경로가 안정적으로 동작하도록
   Windows 실행 진입점 정리
4. provider 또는 GeekMagic 일시 장애 후 자동 복구 검증
5. 장시간 연속 실행과 정상 종료 확인

### Phase 7 — Windows 알림 영역 실행 및 인계 — 완료

1. 창 없는 알림 영역 앱과 상태·로그·종료 메뉴
2. 바탕화면 바로가기 설치·제거 명령
3. 숨김 실행, 작업 디렉터리, 중복 실행 방지와 로그 경로 확인
4. 바로가기 실행 후 실제 사용량 조회와 GeekMagic 전송 확인
5. 설치·업데이트·종료·문제 해결 절차를 README에 정리

Phase 7까지 완료하면 Windows 버전을 일상적으로 사용할 수 있는 상태로 마무리합니다.
그 이후 Mac을 사용할 수 있을 때 Phase 8과 Phase 9를 진행합니다. Windows Phase 7은
바로가기 숨김 실행, 알림 영역 동작, 장치 갱신 및 정상 종료까지 실기 확인을 마쳤습니다.
