# VERReport

C/C++ 검증 결과(GTest, LLVM 커버리지, Cppcheck, Lizard)를 읽어 HTML 대시보드와 상세 결과 페이지를 만드는 Python 도구입니다.
입력 구조는 [ClaudeClang](https://github.com/Seokjin-Jang/ClaudeClang) CI가 만드는 `reports/` 디렉터리를 따릅니다.

## 입력 (`reports/`)

| 도구 | 경로 | 생성 명령 (ClaudeClang `ci/`) |
|---|---|---|
| Google Test | `{unit,integration,tdd}/results.xml` | `--gtest_output=xml:` |
| LLVM 커버리지 | `{unit,integration,tdd}/export.json` | `llvm-cov export -format=text` |
| Cppcheck | `cppcheck.xml` | `cppcheck --xml --xml-version=2` |
| Lizard | `lizard.xml` | `lizard -C 10 -L 80 --warnings_only` 결과를 checkstyle XML로 변환 |

## 설치

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux: .venv/bin/python
```

## 사용

```bash
verreport build -c verreport.toml -o report                       # 설정 파일의 reports_dir 사용
verreport build -c verreport.toml -r ../ClaudeClang/reports -o report
```

설정은 `verreport.toml`을 참고하세요. 스위트별 합격 기준(성공률, 커버리지 지표와 기준값)과 Lizard 임계값을 지정합니다.

| 옵션 | 설명 |
|---|---|
| `--build-id`, `--commit` | 빌드 번호/커밋 표시 (예: Jenkins `BUILD_NUMBER`, `GIT_COMMIT`) |
| `--build-time` | 빌드 시각(ISO). 생략 시 GTest 실행 시각 → reports 수정 시각 |
| `--fail-on-verdict` | 전체 판정이 FAIL 이면 종료 코드 1 |
| `--no-demangle` | C++ 함수명 디맹글 생략 (`llvm-cxxfilt`/`c++filt` 가 없으면 자동 생략) |

출력은 `index.html`(대시보드)과 도구별 상세 페이지, `assets/style.css`로 된 정적 HTML입니다.

| 페이지 | 계층 |
|---|---|
| `gtest.html` | 스위트 → 테스트 그룹 → 테스트 케이스(실패 메시지, 위치) |
| `coverage.html` | 스위트 → 모듈 → 파일 → 함수(영역·분기 커버리지, 호출 횟수) |
| `cppcheck.html` | 규칙별 집계, 모듈 → 파일 → 지적(라인, 심각도, 규칙, CWE) |
| `lizard.html` | 모듈 → 파일 → 함수(CCN, 길이, NLOC, 인자), 전체 초과 함수 목록 |

문제가 있는 모듈/그룹은 처음부터 펼쳐져 있습니다.
스크립트, 인라인 스타일, 외부 리소스를 쓰지 않아서 Jenkins HTML Publisher의 기본 CSP에서도 그대로 보입니다.

## 테스트

```bash
.venv/Scripts/python -m pytest
```

## 진행 상황

- [x] 1단계: 골격, 데이터 모델, 설정, 샘플 입력
- [x] 2단계: 도구별 파서
- [x] 3단계: 모듈/파일/함수 집계, 판정
- [x] 4단계: 대시보드
- [x] 5단계: 도구별 상세 페이지
- [ ] 6단계: 예외 처리, 성능, 문서
