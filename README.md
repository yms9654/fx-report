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
