# VERReport

C/C++ 검증 결과를 읽어 **HTML 대시보드와 도구별 상세 결과 페이지**를 만드는 Python 도구입니다.

| 대상 | 내용 |
|---|---|
| Google Test | 테스트 성공/실패/건너뜀, 실패 메시지와 위치 |
| LLVM 커버리지 | 라인/함수/분기/MC/DC/영역 커버리지 (모듈 → 파일 → 함수) |
| Cppcheck | 규칙 위반 (모듈 → 파일 → 라인) |
| Lizard | 순환복잡도 10 초과, 함수 길이 80 초과 함수 (모듈 → 파일 → 함수) |

입력 구조는 [ClaudeClang](https://github.com/Seokjin-Jang/ClaudeClang) CI가 만드는 `reports/` 디렉터리를 따르고,
합격/불합격 판정은 ClaudeClang `ci/check_*.py`와 같은 규칙을 씁니다.

---

## 빠른 시작

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"      # Linux: .venv/bin/python
.venv/Scripts/verreport build -c verreport.toml -o report
```

`report/index.html`을 브라우저로 열면 샘플 데이터(`samples/reports/`)로 만든 리포트를 볼 수 있습니다.

ClaudeClang 실제 결과는 `examples/claudeclang.toml`을 씁니다. 두 저장소를 나란히 클론했다고 가정하며,
모듈을 아키텍처 컴포넌트(C-VAL, C-STA, C-ARB, C-CTL)로 묶고 UTC 컨테이너의 GTest 시각을 현지 시각으로 바꿉니다.

```bash
verreport build -c examples/claudeclang.toml -o report --build-id 128 --commit 3f2a9c1
verreport build -c examples/claudeclang.toml -r 다른/reports -o report     # reports 위치만 바꿀 때
```

요구 사항: Python 3.11 이상, Jinja2. C++ 함수명 디맹글에는 `llvm-cxxfilt` 또는 `c++filt`가 있으면 사용합니다(없으면 원래 이름 표시).

---

## 입력 (`reports/`)

| 도구 | 경로 | 생성 명령 (ClaudeClang `ci/`) |
|---|---|---|
| Google Test | `{unit,integration,system,tdd}/results.xml` | `<테스트 실행 파일> --gtest_output=xml:...` |
| LLVM 커버리지 | `{unit,integration,system,tdd}/export.json` | `llvm-cov export -format=text` |
| Cppcheck | `cppcheck.xml` | `cppcheck --xml --xml-version=2` |
| Lizard | `lizard.xml` | `lizard -C 10 -L 80 --warnings_only` 출력을 `ci/lizard_report.py`로 checkstyle XML 변환 |

- 경로는 `verreport.toml`의 `[inputs]`에서 바꿀 수 있습니다.
- docker(`/workspace/...`)나 Jenkins 워크스페이스의 절대 경로는 `src/`, `tests/`부터 잘라 저장소 기준 경로로 통일합니다(`project.path_anchors`).
- 결과 파일이 **없으면** 해당 항목은 N/A(경고)이고 전체 판정에서 빠집니다.
- 결과 파일이 **있는데 읽지 못하면** 해당 항목은 FAIL이고 사유가 리포트에 표시됩니다. 깨진 결과가 통과로 보이지 않게 하기 위해서입니다.

---

## 명령행

```
verreport build [-c 설정.toml] [-r reports 디렉터리] [-o 출력 디렉터리] [옵션]
```

| 옵션 | 설명 |
|---|---|
| `-c`, `--config` | 설정 파일 (생략 시 기본값) |
| `-r`, `--reports` | reports 디렉터리. 설정의 `inputs.reports_dir`보다 우선 |
| `-o`, `--output` | 출력 디렉터리 (기본 `report`) |
| `--build-id`, `--commit` | 빌드 번호/커밋 표시 (예: Jenkins `BUILD_NUMBER`, `GIT_COMMIT`) |
| `--build-time` | 빌드 시각(ISO 8601). 생략 시 GTest 실행 시각 중 가장 이른 값 → reports 수정 시각. 화면에는 현지 시각과 오프셋(예: `UTC+09:00`)으로 표시 |
| `--fail-on-verdict` | 전체 판정이 FAIL이면 종료 코드 1 |
| `--strict` | 결과 파일을 읽지 못하면 리포트를 만들지 않고 종료 코드 2 |
| `--no-demangle` | C++ 함수명 디맹글 생략 |

| 종료 코드 | 의미 |
|---|---|
| 0 | 리포트 생성 (판정과 무관, `--fail-on-verdict` 없을 때) |
| 1 | 리포트 생성, 전체 판정 FAIL (`--fail-on-verdict`) |
| 2 | 설정 오류, 출력 실패, `--strict`에서 결과 파일 오류 |

---

## 설정 (`verreport.toml`)

```toml
[project]
name = "ClaudeClang"
source_root = "."                   # 경로를 이 기준 상대 경로로 정규화
path_anchors = ["src", "tests"]     # 다른 머신/컨테이너 절대 경로를 이 디렉터리부터 자름
test_timezone = "UTC"               # GTest 시각이 기록된 시간대 ("UTC", "+09:00", "UTC-5", IANA 이름)

[inputs]
reports_dir = "../ClaudeClang/reports"
suites = ["unit", "integration", "system", "tdd"]
# gtest = "{suite}/results.xml"   llvmcov = "{suite}/export.json"
# cppcheck = "cppcheck.xml"       lizard = "lizard.xml"

[thresholds]
lizard_ccn = 10                     # CCN 이 값 초과면 위반
lizard_length = 80                  # 함수 길이 이 값 초과면 위반
cppcheck_gate_paths = ["src/"]      # 이 경로 아래 지적만 판정 (나머지는 참고로 표시)
cppcheck_ignore_severities = ["information"]

[thresholds.suites.unit]
pass_rate = 100.0
coverage_metric = "mcdc"            # lines | functions | branches | mcdc | regions
coverage_min = 100.0

[thresholds.suites.integration]
pass_rate = 100.0
coverage_metric = "functions"
coverage_min = 100.0

[thresholds.suites.system]
pass_rate = 100.0                   # 요구사항 커버리지는 ClaudeClang ci/check_traceability.py 가 검사

[thresholds.suites.tdd]
pass_rate = 100.0                   # 커버리지 기준 없음: 보고만 함

[modules]
"src/core" = "Core"                 # 디렉터리
"src/arbiter" = "C-ARB 판정기"       # 확장자 없는 경로: src/arbiter.c, src/arbiter.h
"src/eclp_types.h" = "공통"          # 파일 하나
```

모듈 규칙: `[modules]`의 가장 긴 키가 먼저 적용되고, 매핑이 없으면 `src/<모듈>/...`은 `<모듈>`,
`src` 바로 아래 파일은 확장자를 뗀 파일 이름(`arbiter.c`, `arbiter.h` → `arbiter`), 그 밖은 `tests/unit`처럼 앞 두 단계입니다.

GTest는 시간대 없이 실행 환경의 시각을 기록합니다. UTC 컨테이너에서 테스트를 돌렸다면 `test_timezone = "UTC"`를 지정해야
빌드 일시가 9시간 어긋나지 않습니다(한국 기준).

알 수 없는 키, 범위를 벗어난 값(예: `coverage_min = 120`), 함께 써야 하는 값의 누락은 **오류**로 처리합니다.
오타가 조용히 기본값으로 바뀌어 다른 기준으로 판정되는 일을 막기 위해서입니다.

---

## 판정 규칙

| 항목 | FAIL 조건 |
|---|---|
| 테스트 | 실패(failure/error) 1건 이상, 성공률 < `pass_rate`, 실행된 테스트 0건 (건너뜀은 경고) |
| 커버리지 | `coverage_metric`이 결과에 없음, 측정 대상 0건, 기준 미달 (반올림 없이 비교) |
| Cppcheck | `cppcheck_gate_paths` 아래에서 `cppcheck_ignore_severities`가 아닌 지적 1건 이상 |
| Lizard | CCN > `lizard_ccn` 또는 길이 > `lizard_length`인 함수 1개 이상 |
| 공통 | 결과 파일을 읽지 못함 |

전체 판정은 하나라도 FAIL이면 FAIL, 모두 N/A면 N/A, 그 외 PASS입니다.

---

## 출력

| 파일 | 내용 |
|---|---|
| `index.html` | 대시보드: 빌드 일시/번호/커밋, 전체 판정과 사유, 항목별 요약 표, 도구별 차트 카드와 상세 결과 버튼, 조치가 필요한 파일 |
| `gtest.html` | 스위트 → 테스트 그룹 → 테스트 케이스 (실패 메시지, 위치) |
| `coverage.html` | 스위트 → 모듈 → 파일 |
| `cov/<스위트>-<모듈>.html` | 모듈의 파일 → 함수 (영역·분기 커버리지, 호출 횟수). 파일 이름은 ASCII만 쓰고, 한글 모듈 이름에는 짧은 해시를 붙임 |
| `cppcheck.html` | 규칙별 집계, 모듈 → 파일 → 지적 (라인, 심각도, 규칙, CWE, 판정 대상/참고) |
| `lizard.html` | 모듈 → 파일 → 함수 (CCN, 길이, NLOC, 인자), 전체 초과 함수 목록 |
| `assets/style.css` | 스타일 |

- 펼치기는 `<details>`를 쓰고, 문제가 있는 모듈/그룹은 처음부터 펼쳐져 있습니다.
- **스크립트, 인라인 스타일, 외부 리소스를 쓰지 않습니다.** Jenkins HTML Publisher의 기본 CSP에서도 그대로 보이고, 오프라인에서도 열립니다.
  그래서 표 정렬/검색 기능은 없고, 미리 정한 순서(문제가 큰 순)로 정렬되어 있습니다.
- 다크 모드는 OS 설정을 따르며, 인쇄용 스타일이 있습니다.
- llvm-cov는 함수별 라인/MC/DC 요약을 내보내지 않으므로, 함수 단위는 영역·분기 커버리지와 호출 횟수로 표시합니다.

---

## Jenkins 연동

ClaudeClang 빌드 이미지(Ubuntu 24.04, Python 3.12, LLVM)에서 실행하면 C++ 함수명도 디맹글됩니다.

1. `examples/claudeclang.toml`을 ClaudeClang 저장소 루트에 `verreport.toml`로 복사하고, 경로 두 줄을 저장소 기준으로 바꿉니다.
   pip로 설치한 VERReport에는 `examples/`가 없으므로 설정은 ClaudeClang 쪽에 둡니다.

   ```toml
   source_root = "."
   reports_dir = "reports"
   ```

2. `Jenkinsfile`의 `post { always { ... } }`에 다음을 추가합니다.

```groovy
sh '''
    python3 -m venv .verreport && .verreport/bin/pip install -q git+https://github.com/Seokjin-Jang/VERReport.git
    .verreport/bin/verreport build -c verreport.toml -o reports/verreport \
        --build-id "$BUILD_NUMBER" --commit "$GIT_COMMIT"
'''
publishHTML(target: [
    reportDir: 'reports/verreport', reportFiles: 'index.html',
    reportName: 'Verification Report',
    keepAll: true, allowMissing: true, alwaysLinkToLastBuild: true
])
```

리포트 생성 실패가 빌드 결과를 바꾸지 않게 하려면 `--fail-on-verdict` 없이 실행하고, 판정은 기존 `Verdict` 단계에 맡깁니다.

---

## 성능

`scripts/gen_large_sample.py`로 만든 대용량 입력에서 측정한 값입니다 (Windows 11, Python 3.12, 디맹글 생략).

| 입력 | 값 |
|---|---|
| 파일 / 함수 (스위트당) | 2,000 / 30,000 |
| GTest 테스트 (스위트당) | 3,000 |
| Cppcheck 지적 / Lizard 초과 함수 | 5,000 / 800 |
| 입력 크기 | 약 42 MB |

| 결과 | 값 |
|---|---|
| 실행 시간 | 약 6.4초 |
| 최대 메모리 | 약 120 MB |
| `coverage.html` | 3.9 MB |
| 모듈 페이지 (`cov/`) | 150개, 각 400 KB 이하 |
| `gtest.html` / `cppcheck.html` | 2.8 MB / 3.6 MB |

함수 상세를 한 페이지에 모두 넣으면 `coverage.html`이 100 MB를 넘어 브라우저에서 열기 어렵기 때문에 모듈별 페이지로 나눕니다.
대시보드의 모듈별 막대는 상위 8개만 그리고 나머지는 "외 N개 모듈"로 묶습니다.

```bash
python scripts/gen_large_sample.py /tmp/large
verreport build -c verreport.toml -r /tmp/large -o /tmp/large_out
```

---

## 개발

```
src/verreport/
  cli.py          명령행
  config.py       설정 로딩/검증
  models.py       도구 공통 데이터 모델
  paths.py        경로 정규화
  parsers/        gtest, llvmcov, cppcheck, lizard 파서
  loader.py       입력 읽기 (오류 격리)
  aggregate.py    모듈/파일/함수 집계, 판정
  view.py         대시보드 화면 모델
  detail.py       상세 페이지 화면 모델
  render.py       Jinja2 렌더링
  templates/      HTML 템플릿
  static/         style.css
samples/reports/  샘플 입력 (실제 도구 출력 형식)
scripts/          대용량 샘플 생성기
tests/            pytest
```

```bash
.venv/Scripts/python -m pytest
```

새 도구를 추가하려면 `parsers/`에 파서를 만들고 `models.py`의 공통 모델로 변환한 뒤, `loader.py`, `aggregate.py`, 화면 모델과 템플릿에 연결합니다.
