# Ranking formula v1

## 후보 자격

비교 후보는 anchor와 같은 카테고리·세부 카테고리·정규화 품목명에 속하고
활성 상태여야 함. anchor 자신과 중복 물품 ID는 제외함. FTS5와 TF-IDF는 이
exact 후보 집합을 넓히지 않음.

## 점수

활성 feature의 가중합을 활성 가중치 합으로 나눔.

```text
score = (0.35L + 0.20F + 0.35U + 0.10P) / active_weight_sum
```

| 기호 | 의미 | 가중치 |
|---|---|---:|
| L | 옵션 텍스트 lexical similarity | 0.35 |
| F | 옵션 텍스트 fuzzy similarity | 0.20 |
| U | 구조화 규격 similarity | 0.35 |
| P | 비교 가능한 가격 similarity | 0.10 |

anchor에 옵션, 구조화 규격, 유효 가격이 없는 feature는 분모에서도 제외함.
후보 쪽 근거가 빠진 경우에는 0점 근거로 처리하고 coverage에 반영함.

양수 수치와 가격의 유사도는 값의 비율에 대한 대칭 log-distance decay를
사용함. 가격은 양수 금액이고 단위가 정규화되어 서로 비교 가능할 때만 활성화됨.
모든 표시 점수는 Decimal round-half-even으로 소수점 6자리까지 고정함.

## 순서와 3개 slot

정렬 순서는 다음과 같음.

1. 총점 내림차순
2. 구조화 규격 점수 내림차순
3. lexical 점수 내림차순
4. fuzzy 점수 내림차순
5. 가격 log-distance 오름차순
6. 물품 ID 오름차순

항상 1~3번 slot을 반환함. 실제 후보가 부족하면 해당 slot은
`insufficient_candidates`, 비교 근거 자체가 없으면 `no_comparison_evidence`로
표시함.
