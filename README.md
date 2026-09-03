# fx-report — 원/달러 매도 타이밍 리포트

매일 자동으로 갱신되는 USD/KRW 매도 전략 페이지.
**https://yms9654.github.io/fx-report/**

## 파이프라인

```
cron ─▶ run_daily.sh
         ├─ build/fetch_data.py        네이버 매매기준율(서울) → data.json   (폴백: ECB/frankfurter)
         ├─ build/update_narrative.py  claude -p 로 분석 재작성 → narrative.json
         ├─ build/render.py            data + narrative + template → docs/index.html
         └─ git commit && push         → GitHub Pages 자동 배포
```

## 화면 구성

결론부터 나오고, 근거는 접어둔다.

```
오늘의 지시   판다 / 기다린다 + 현재·다음·손절
계획          매도 사다리 (실제 가격 눈금)
주간 확률     4주 상승/하락 + 계획가 도달 확률
최근 흐름     일별 종가 차트
왜 이렇게 보나 [접힘] 힘겨루기 · 시나리오 · 일정 · 체결 비용
```

## 오늘의 지시

페이지 최상단에 현재가를 계획과 대조한 결과가 한 단어로 나온다.

| 현재가 위치 | 지시 |
|---|---|
| 손절 구간 안 | **판다** — 잔여 전량 |
| 매도 구간 안 | **판다** — 그 구간의 계획 비중 |
| 그 사이 | **기다린다** — 오늘은 아무것도 하지 않음 |

`build/render.py` 의 `decide()` 가 `narrative.json` 의 사다리 구간·트리거만 보고
결정한다. Claude 산문이 아니라 숫자에서 나오므로 매일 일관된다.

## 주간 확률

앞으로 4주, 주 단위로 상승/하락 확률과 계획 가격 도달 확률을 계산한다.

- **변동성**: `data.json` 일별 종가의 로그수익률 표준편차 (실측)
- **드리프트**: `narrative.json` 의 `scenario.ev` 를 한 달 기대값으로 보고 역산 (분석가 견해)
- **상승 확률**: `Φ(μ√T / σ)` — 로그정규 종점 분포
- **도달 확률**: 반사원리 기반 배리어 히트 확률. 기간 안에 *한 번이라도* 닿을 확률이라
  종점 확률보다 항상 크고, 기간이 길수록 단조증가한다.

계산은 `build/render.py` 의 `weekly_probs()` 에 있다. 실측 변동성 × 분석 드리프트 조합이라
드리프트가 틀리면 확률도 같이 틀린다. 페이지에 가정을 함께 표기한다.

## 피드백

페이지 하단 폼 → GitHub 이슈. 정적 페이지라 서버가 없으므로 폼 내용을
`issues/new?labels=&title=&body=` URL로 조립해 GitHub 작성 화면을 연다.
제출은 사용자가 확인 후 누른다 (GitHub 계정 필요).

라벨: `도움됨` `안맞음` `제안` `오류`

본문에는 **제출 시점의 컨텍스트가 자동 첨부**된다 — 리포트 날짜, 현재가,
그날의 지시, 트리거 3종, 데이터 수집 시각, 화면폭, 브라우저.
"그때 뭐라고 나왔길래 그런 말을 하는가"를 재구성할 수 있어야 피드백이 쓸모 있다.

### 익명 제출 (기본)

`config.json` 의 `feedback_endpoint` 가 설정되어 있으면 폼이 그 주소로 POST 하고,
Cloudflare Worker 가 GitHub API 로 이슈를 만든다. 방문자는 계정이 필요 없다.

```
브라우저 ─POST─▶ Worker ─GitHub API─▶ 이슈 생성
                  │
                  ├ 허니팟(website 필드) — 봇은 성공한 척하고 버림
                  ├ 유형 화이트리스트 4종
                  ├ 본문 2000자 상한, < > 이스케이프
                  └ IP당 시간당 5건 (KV)
```

엔드포인트가 비어 있으면 자동으로 GitHub 링크 방식으로 떨어진다.
익명 전송이 실패해도 링크와 복사 버튼이 노출되어 길이 끊기지 않는다.

배포: `./setup_feedback.sh` — Cloudflare 로그인과 토큰 입력만 직접 하면 나머지는 자동.

## 안전장치

- 데이터 수집 실패 → 직전 `data.json` 유지, 페이지에 경과일수 표시
- 분석 재작성 실패 → 직전 `narrative.json` 유지, 페이지에 "직전 분석 유지" 표시
- Claude 출력은 스키마 검증(트리거 순서, 사다리 범위, 현재가 포함 여부 등) 통과 시에만 반영
- 모든 쓰기는 tmp → rename 원자적 교체

## 수동 실행

```bash
./run_daily.sh            # 전체
FX_SKIP_CLAUDE=1 ./run_daily.sh   # 데이터+렌더만 (분석 재작성 생략)
FX_MODEL=opus ./run_daily.sh      # 분석 모델 변경 (기본 sonnet)
```

투자 권유가 아닙니다.
