# 교정/레이아웃 프리뷰 스타일 옵션 추가 구현안

대상: `modules/nf_orchestrator/debug_ui.html`의 **교정 + 레이아웃** 패널(레이아웃 프리뷰).

목표: 프리뷰에서 **배경색 / 폰트 / 글자 크기 / 좌우 여백 / 줄 간격(행간) / 자간**을 조절할 수 있게 한다.
서버 API/저장 데이터에는 영향이 없고, UI 프리뷰에만 적용한다.

---

## 1) 현재 구현 요약

- 입력 요소
  - `#layout-letter`(자간, `em`)
  - `#layout-line`(행간, `line-height`)
  - `#layout-text`(미리보기 텍스트)
  - `#layout-preview`(렌더 대상)
- 렌더 로직
  - `renderPreview()`가 `letterSpacing`, `lineHeight`를 `#layout-preview`에 적용.
  - `state.lintItems`가 있으면 `span.lint`로 해당 구간을 감싸 underline/tooltip 유사 강조를 수행.

---

## 2) UI 설계(HTML) — 권장 구성

기존 “자간/행간” 슬라이더 줄에 아래 컨트롤을 추가하거나, 바로 아래에 1줄을 더 만든다.

### 2.1 배경색

- `input[type="color"]#layout-bg`
  - 기본값: `#ffffff`
  - (선택) “투명”이 필요하면 별도 토글을 추가하고, 체크 시 `backgroundColor = "transparent"` 처리.
  - (권장) 배경색에 따라 텍스트 색을 자동으로 대비되게 설정(자동 대비).

### 2.2 폰트(프리셋 + 커스텀)

- 프리셋: `select#layout-font-preset`
  - `system` (기본)
  - `sans_kr` (한글 가독성 위주)
  - `serif`
  - `mono`
- 커스텀: `input[type="text"]#layout-font-custom`
  - placeholder 예: `system-ui, "Noto Sans KR", "Malgun Gothic", sans-serif`
  - 동작(권장): 프리셋이 `custom`일 때만 입력을 활성화하고 적용.

프리셋이 반환해야 하는 값(예시 CSS font-family):

- `system`: `system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif`
- `sans_kr`: `system-ui, "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", "Noto Sans CJK KR", sans-serif`
- `serif`: `ui-serif, Georgia, "Times New Roman", Times, serif`
- `mono`: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`

### 2.3 글자 크기(px)

- `input[type="range"]#layout-font-size`
  - 범위(권장): `10..32`(step `1`)
  - 기본값(권장): `14`
  - 표시(선택): `span#layout-font-size-value`로 현재 값 표기

### 2.4 좌우 여백(px)

프리뷰의 “페이지 여백”을 흉내 내기 위해 `margin`보다 `padding`이 UX에 적합하다(테두리/배경이 함께 이동).

- 단일 슬라이더(권장): `input[type="range"]#layout-padding-x`
  - 범위(권장): `0..80`(step `2`)
  - 기본값(권장): `12`(기존 `.preview` 기본 padding과 일치)
  - 적용: `preview.style.paddingLeft/right`
- 좌/우 분리(선택): `#layout-padding-left`, `#layout-padding-right`

### 2.5 리셋

- 버튼(권장): `button#layout-style-reset`
  - 동작: 위 옵션들을 기본값으로 되돌리고 `renderPreview()` 호출.

---

## 3) 적용 방식(JS) — 권장 로직

### 3.1 스타일 적용은 `renderPreview()`에 통합

`renderPreview()` 초반에 아래를 수행:

- `fontFamily`: 프리셋이 `custom`이면 커스텀 값을, 아니면 프리셋 값을 `preview.style.fontFamily`에 적용
- `fontSize`: `preview.style.fontSize = fontSizePx + "px"`
- `backgroundColor`: 투명 체크 시 `"transparent"`, 아니면 color 값
- (권장) 배경색 기반 자동 대비: `preview.style.color`를 흰/검 계열로 자동 설정
- `paddingLeft/right`: `paddingX + "px"`
- 기존 동작 유지: `letterSpacing`, `lineHeight`, lint 강조 렌더

### 3.2 이벤트 바인딩

아래 요소들에 `input`/`change` 이벤트로 `renderPreview()` 연결:

- `#layout-bg`, `#layout-bg-transparent`(옵션)
- `#layout-font-preset`, `#layout-font-custom`(옵션)
- `#layout-font-size`
- `#layout-padding-x`(또는 left/right)
- 기존: `#layout-letter`, `#layout-line`, `#layout-text`

---

## 4) localStorage 저장(권장)

리로드 시 작업 흐름이 끊기지 않도록, 레이아웃 옵션을 localStorage에 저장한다.

- 키(예시): `nf_layout_style_v1`
- 값(예시 JSON):
  - `bg`, `bgTransparent`, `fontPreset`, `fontCustom`, `fontSizePx`, `paddingX`
  - 기존 슬라이더도 포함하려면 `letterSpacingEm`, `lineHeight`를 함께 저장 가능

구현 형태:

- `loadLayoutStyle()`에서 localStorage → 각 input value 세팅 → `renderPreview()`
- `saveLayoutStyle()`에서 각 input value → localStorage 저장
- 이벤트에서 `saveLayoutStyle(); renderPreview();` 패턴으로 연결

---

## 5) 엣지 케이스/주의점(권장 대응)

- 어두운 배경: 텍스트가 안 보일 수 있음
  - 대응(권장): 배경 밝기(luminance)로 텍스트 색 자동 변경 또는 “테마 프리셋(밝음/어두움)” 제공
- 글꼴 미설치: 지정한 폰트가 없으면 폴백 스택을 사용(프리셋 설계로 완화)
- 큰 여백/큰 글자: 프리뷰 높이가 부족할 수 있음
  - 대응: `#layout-preview`의 스크롤(`overflow`)을 유지하거나 최대 높이/리사이즈 정책을 명시
- lint 강조 가독성: 배경색에 따라 `.lint`의 RGBA가 잘 안 보일 수 있음
  - 대응(선택): `.lint`는 underline 중심(`border-bottom`)으로 유지하고 배경 alpha를 낮추거나 CSS 변수로 분리

---

## 6) 검증 체크리스트(수동)

1. `run_debug_ui.py`로 UI 실행 후, 옵션 변경 시 `#layout-preview`에 즉시 반영되는지 확인
2. `PROOFREAD`로 lint 수신 후에도( `span.lint` 렌더 상태) 폰트/배경/크기/여백이 유지되는지 확인
3. 새로고침 후에도(localStorage) 값이 복원되는지 확인
