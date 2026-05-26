# references/ — 레퍼런스 이미지 및 배치 예시

`ref_image_loader` 노드가 카테고리별로 읽는 폴더.

## 구조

```
references/
├── images/{카테고리}/ref_*.jpg|png|webp   ← 조감도 레퍼런스 이미지
└── layouts/{카테고리}/layout_*.json       ← 이전 성공 배치 예시
```

## 이미지 규칙

- 파일명: `ref_001.jpg`, `ref_002.png` 등 (`ref_` 접두사 필수)
- 내용: 해당 카테고리 팝업스토어 **조감도** (위에서 내려다보는 시점)
- 카테고리당 3~5장 권장
- Agent 3(design)이 "이런 느낌으로 배치해" 참고하는 용도

## 레이아웃 JSON 규칙

- 파일명: `layout_001.json` 등 (`layout_` 접두사 필수)
- 내용: 이전에 잘 된 배치 결과 (placed_objects 형태)

```json
{
  "category": "캐릭터 IP",
  "floor_area_sqm": 50,
  "placed_objects": [
    {"object_type": "counter", "zone_label": "deep_zone", "direction": "wall_facing"},
    {"object_type": "character_bbox", "zone_label": "entrance_zone", "direction": "wall_facing"}
  ]
}
```

## 카테고리 폴더

| 폴더명 | 카테고리 |
|---|---|
| 캐릭터IP | 캐릭터 IP |
| 패션브랜드 | 패션 브랜드 |
| FB | F&B |
| 뷰티코스메틱 | 뷰티/코스메틱 |
| 테크전자제품 | 테크/전자제품 |
| 아트전시 | 아트/전시 |
| 엔터팬미팅 | 엔터/팬미팅 |
| 기타 | 기타 (fallback) |
