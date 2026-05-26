"""
배치 파이프라인 실행 서비스.

- place_large: HTTP 전용 — place_large_graph (sub-graph) 호출 wrapper
- place_small: 소·중형 파이프라인 (rendy 영역, 직렬 호출 유지)
- refresh_ref_point_status: fallback 이후 최종 placed_raw 로 ref_point_status.json 재덤프

2026-05-02 graph 랭그래프화 단계 6 — place_large_stages 삭제, place_large 가 sub-graph invoke wrapper 로 축소.
"""
import logging

from app.constants import SMALL_AREA_THRESHOLD_MM2
from app.debug import dump_debug
from app.serializers.place_serializer import format_place_response
from app.services.intent_service import (
    apply_removal_intents,
    apply_reorient_intents,
    apply_resize_intents,
    filter_eligible_for_addition,
    resolve_strategy,
)

logger = logging.getLogger(__name__)


# ── large place — sub-graph 컴파일 (모듈 싱글톤) ─────────────────────
# 첫 호출 시 lazy 컴파일 → 이후 재사용. invoke wrapper 가 매번 컴파일하면 비용 ↑
_place_large_graph_compiled = None


def _get_place_large_graph():
    """place_large_graph 의 lazy 컴파일 싱글톤."""
    global _place_large_graph_compiled
    if _place_large_graph_compiled is None:
        from app.graph import compile_place_large_graph
        _place_large_graph_compiled = compile_place_large_graph()
    return _place_large_graph_compiled


def place_large(state: dict) -> dict:
    """대형 배치 파이프라인 — place_large_graph (sub-graph) invoke wrapper.

    2026-05-02 graph 랭그래프화 단계 6 — 기존 직렬 호출 (place_large_stages) 삭제,
    sub-graph invoke 로 축소. token reset/dump + format_place_response 만 wrapper 책임.
    """
    from app.token_tracker import dump_and_reset as _token_dump
    from app.token_tracker import reset as _token_reset

    # 1. invoke 전 — 토큰 카운터 초기화 (이전 단계 잔재 제거)
    _token_reset()

    # 2. sub-graph invoke — 모든 노드 흐름 graph 안에서 처리
    graph = _get_place_large_graph()
    final_state = graph.invoke(state)

    # 3. invoke 후 — 토큰 사용량 덤프 (Java INSERT 용)
    try:
        final_state["token_usage_summary"] = _token_dump()
    except Exception as _e:
        logger.warning(f"[place:large] token dump 실패: {_e}")
        final_state["token_usage_summary"] = {}

    # 4. 구조화 리포트 JSON 생성 (DB 저장 + 프론트 리포트 패널용)
    from app.services.report_service import build_report_json
    try:
        final_state["report_json"] = build_report_json(final_state)
    except Exception as _e:
        logger.warning(f"[place:large] report_json 생성 실패: {_e}")
        final_state["report_json"] = {}

    # 5. 응답 포맷
    return format_place_response(final_state)


def place_small(state: dict) -> dict:
    """소·중형 배치 파이프라인."""
    # 전처리 / 후처리 노드만 직접 호출. agent 구간 (design ~ placement_reviewer) 은
    # nodes_small/agent_graph 의 sub-graph 가 자율 처리.
    # verify 는 early return 분기 (intent_parse_error / NOOP+locked) 에서 직접 호출 — 유지.
    # 1-3 (#533) C1: pathing_validator 는 agent_graph 9번째 노드로 진입.
    # 본 함수는 early return path (intent_parse_error / NOOP+locked) 에서만 직접 호출.
    from app.nodes_small import (
        object_selection, intent_parser, verify,
        pathing_validator, report_gen,
        ref_image_loader, ref_image_analyzer,
    )
    from app.token_tracker import reset as _token_reset
    _token_reset()  # 이전 단계(detect/space_data) 잔재 제거 — place 파이프라인 만 집계

    # 레퍼런스 이미지 로드 + 분석 (design.py 프롬프트에 주입됨)
    state.update(ref_image_loader.run(state))
    logger.info(f"[place:small] ref_images: {len(state.get('reference_images', []))}")
    state.update(ref_image_analyzer.run(state))
    logger.info(f"[place:small] ref_analysis: {bool(state.get('ref_analysis'))}")

    state.update(intent_parser.run(state))

    # ── LLM 호출 실패 → 기존 배치 유지 + 에러 사유 반환 ──
    if state.get("intent_parse_error") and state.get("user_requirements") and state.get("locked_objects"):
        locked = list(state.get("locked_objects") or [])
        state["placed_objects"] = locked
        state["failed_objects"] = []
        state["design_intents"] = []
        state["placed_partitions"] = []
        state["ref_quality_score"] = 0.0
        logger.warning(f"[place:small] intent_parse_error — 기존 배치 유지: {state['intent_parse_error']}")
        dump_debug("resolved_intents.json", {
            "resolved_intents": [],
            "placement_strategy": "ERROR",
            "intent_parse_error": state.get("intent_parse_error"),
            "user_requirements": state.get("user_requirements", ""),
        })
        state.update(verify.run(state))
        state.update(pathing_validator.run(state))
        state.update(report_gen.run(state))
        try:
            from app.token_tracker import dump_and_reset
            state["token_usage_summary"] = dump_and_reset()
        except Exception as _e:
            logger.warning(f"[place:small] token dump 실패: {_e}")
            state["token_usage_summary"] = {}
        from app.services.report_service import build_report_json
        try:
            state["report_json"] = build_report_json(state)
        except Exception as _e:
            logger.warning(f"[place:small] report_json 생성 실패: {_e}")
            state["report_json"] = {}
        return format_place_response(state)

    # 처리 전 원본 보존 — 최종 실패 시 요구사항과 매핑하기 위해
    state["_original_resolved_intents"] = list(state.get("resolved_intents") or [])
    apply_removal_intents(state)

    # ── Strategy Resolver: action 조합 → 파이프라인 전략 결정 ──
    resolved = state.get("resolved_intents") or []
    strategy = resolve_strategy(resolved)
    state["placement_strategy"] = strategy
    logger.info(f"[place:small] strategy: {strategy}")

    if strategy in ("FULL_RELAYOUT", "PARTIAL_REORIENT"):
        apply_reorient_intents(state, strategy)
    if strategy in ("RESIZE_ONLY", "RESIZE_AND_ADD"):
        apply_resize_intents(state)

    resolved = state.get("resolved_intents") or []
    logger.info(f"[place:small] resolved_intents (after strategy): {len(resolved)}")
    dump_debug("resolved_intents.json", {
        "resolved_intents": resolved,
        "placement_strategy": strategy,
        "intent_parse_fallback": state.get("intent_parse_fallback_reason", ""),
        "locked_objects_count": len(state.get("locked_objects") or []),
        "dimension_overrides": state.get("dimension_overrides") or {},
        "global_direction_hint": state.get("global_direction_hint"),
        "user_requirements": state.get("user_requirements", ""),
    })

    # ── 제거 전용(NOOP) + locked 있음 → design/placement 스킵, 기존 유지 ──
    if strategy == "NOOP" and state.get("locked_objects"):
        locked = list(state.get("locked_objects") or [])
        state["placed_objects"] = locked
        state["failed_objects"] = []
        state["design_intents"] = []
        state["placed_partitions"] = []
        state["ref_quality_score"] = 0.0
        logger.info(f"[place:small] NOOP+locked — design/placement 스킵, {len(locked)}개 유지")
        state.update(verify.run(state))
        state.update(pathing_validator.run(state))
        state.update(report_gen.run(state))
        try:
            from app.token_tracker import dump_and_reset
            state["token_usage_summary"] = dump_and_reset()
        except Exception as _e:
            logger.warning(f"[place:small] token dump 실패: {_e}")
            state["token_usage_summary"] = {}
        from app.services.report_service import build_report_json
        try:
            state["report_json"] = build_report_json(state)
        except Exception as _e:
            logger.warning(f"[place:small] report_json 생성 실패: {_e}")
            state["report_json"] = {}
        return format_place_response(state)

    state.update(object_selection.run(state))
    logger.info(f"[place:small] eligible: {len(state.get('eligible_objects', []))}")

    # ── 추가 모드: eligible_objects를 요청 타입만으로 좁히고 design.py가 전체 맥락에서 재설계 ──
    if state.get("locked_objects") and state.get("resolved_intents"):
        filter_eligible_for_addition(state)

    # ── agent sub-graph invoke (5-5 #490 후속 — nodes_small/agent_graph) ─────
    # design → design_reviewer → partition_placement → placement → verify ↔ fallback
    #   → placement_reviewer → (END or design 재시도)
    # 모든 분기 / 재시도 한도 / slot 양보 hint inject 가 agent_graph 안에서 자율 처리.
    # routes.py 의 conditional 함수가 reviewer 가 박은 status 만 보고 분기.
    from app.nodes_small.agent_graph import AGENT_GRAPH
    agent_result = AGENT_GRAPH.invoke(state)
    state.update(agent_result)

    # ── 디버그 덤프 — graph invoke 후 final state 기준 ──
    _design_dump: dict = {
        "intents": state.get("design_intents", []),
        "eligible_objects": [{"type": o["object_type"], "w": o.get("width_mm"), "d": o.get("depth_mm"), "h": o.get("height_mm")} for o in state.get("eligible_objects", [])],
        "eligible_count": len(state.get("eligible_objects", [])),
        "ref_points_total": len(state.get("reference_points", [])),
        "inaccessible_rooms": len(state.get("inaccessible_polys", [])),
        "venue_type": state.get("venue_type", "unknown"),
        "engine_size": "small" if (state.get("usable_poly").area if state.get("usable_poly") else 0) < SMALL_AREA_THRESHOLD_MM2 else "medium",
    }
    if state.get("design_fallback_reason"):
        _design_dump["design_fallback_reason"] = state["design_fallback_reason"]
        logger.warning(f"[place:small] design fallback: {state['design_fallback_reason']}")
    dump_debug("design_intents.json", _design_dump)

    # 가벽 전용 디버그 덤프 (agent_graph 안 partition_placement 노드가 채운 결과)
    all_rps = state.get("reference_points", [])
    wall_rp_count = sum(1 for rp in all_rps if rp.get("wall_linestring"))
    dump_debug("partition_placement.json", {
        "ref_points_total": len(all_rps),
        "ref_points_with_wall_linestring": wall_rp_count,
        "partitions": [{
            "type": p["object_type"],
            "center": [p["center_x_mm"], p["center_y_mm"]],
            "w": p["width_mm"], "d": p["depth_mm"],
            "rot": p.get("rotation_deg"),
            "anchor_end_mm": p.get("anchor_end_mm"),
            "free_end_mm": p.get("free_end_mm"),
            "anchor_snap_dist": p.get("anchor_snap_dist"),
            "normal_vec": p.get("normal_vec"),
            "wall_vec": p.get("wall_vec"),
            "bbox_corners": p.get("bbox_corners"),
            "front_vec": list(p["front_vec"]) if p.get("front_vec") else None,
            "anchor_key": p.get("anchor_key"),
        } for p in state.get("placed_partitions", [])],
        "partition_ref_points": [{
            "id": rp["id"],
            "coord": [round(rp["coord"][0]), round(rp["coord"][1])],
            "is_partition": rp.get("is_partition"),
            "label": rp.get("label"),
        } for rp in state.get("reference_points", []) if rp.get("is_partition")],
    })

    # ── fallback 이후 ref_point_status 재덤프 (final placed_raw 기준) ──
    refresh_ref_point_status(state)

    # ── 부동선 (#116, F-8 복원) — placed_objects 기반 외곽 복귀 동선 계산 ──
    # placement + fallback 모두 끝난 최종 placed_objects 기반. graceful — 실패 시 빈 list.
    from app.nodes_small import sub_path
    state.update(sub_path.run(state))

    # 1-3 (#533) C1: pathing_validator 는 agent_graph 안에서 처리 — 직접 호출 제거.
    state.update(report_gen.run(state))

    # ── 토큰 사용량 덤프 (token_usage.json) + state 저장 (Java INSERT 용) ──
    try:
        from app.token_tracker import dump_and_reset
        state["token_usage_summary"] = dump_and_reset()
    except Exception as _e:
        logger.warning(f"[place:small] token dump 실패: {_e}")
        state["token_usage_summary"] = {}

    # ── 구조화 리포트 JSON 생성 (DB 저장 + 프론트 리포트 패널용) ──
    from app.services.report_service import build_report_json
    try:
        state["report_json"] = build_report_json(state)
    except Exception as _e:
        logger.warning(f"[place:small] report_json 생성 실패: {_e}")
        state["report_json"] = {}

    return format_place_response(state)


def refresh_ref_point_status(state: dict) -> None:
    """fallback 이후 최종 placed_raw 상태를 ref_point_status.json에 재덤프.

    placement.py 끝에서 1차 덤프했으나 그 이후 fallback이 성공하면 그 기물이 누락됨.
    이 함수가 같은 로직으로 최종 상태를 다시 빌드해 state와 파일 모두 갱신.
    """
    try:
        import json as _json
        import os as _os
        from datetime import datetime as _dt
        _dd = _os.path.join(_os.path.dirname(__file__), "..", "..", "debug_logs", _dt.now().strftime("%Y-%m-%d"))
        _os.makedirs(_dd, exist_ok=True)

        placed_raw = state.get("placed_raw") or []
        ref_points_meta = state.get("reference_points") or []
        slots_meta = state.get("slots") or {}

        # 좌표 + 타입 + 사이즈 룩업 (placement.py와 동일 로직)
        from app.nodes_small.placement import _get_search_radius
        coord_map: dict = {}
        zone_map: dict = {}
        type_map: dict = {}
        size_map: dict = {}
        for rp in ref_points_meta:
            coord_map[rp["id"]] = list(rp["coord"])
            zone_map[rp["id"]] = rp.get("zone_label") or ""
            type_map[rp["id"]] = "ref_point"
            size_map[rp["id"]] = _get_search_radius(rp)
        for slot_key, slot in slots_meta.items():
            if "coord" in slot:
                coord_map[slot_key] = list(slot["coord"])
            elif "x_mm" in slot and "y_mm" in slot:
                coord_map[slot_key] = [slot["x_mm"], slot["y_mm"]]
            zone_map.setdefault(slot_key, slot.get("zone_label") or "")
            type_map.setdefault(slot_key, "slot")
            size_map.setdefault(slot_key, 250.0)

        rp_status: list = []
        for idx, p in enumerate(placed_raw):
            anchor_key = p.get("anchor_key", f"placed_{idx}")
            rp_type = type_map.get(anchor_key, "ref_point" if anchor_key.startswith(("wall_", "iwall_", "center_")) else "slot")
            rp_status.append({
                "id": f"placed_{idx}_{anchor_key}",
                "coord": [round(p.get("center_x_mm", 0), 1), round(p.get("center_y_mm", 0), 1)],
                "zone_label": p.get("zone_label", ""),
                "type": rp_type,
                "size_mm": size_map.get(anchor_key, 250.0 if rp_type == "slot" else 2000.0),
                "status": "success",
                "placed_obj": p.get("object_type", ""),
                "anchor_key": anchor_key,
                "placed_because": p.get("placed_because", ""),  # Phase 구분용
                "rejects": [],
            })

        # rejected/untried는 원본 ref_point_status에서 rejected/untried 항목만 보존
        original = state.get("ref_point_status") or []
        success_keys = {p.get("anchor_key") for p in placed_raw}
        for r in original:
            if r.get("status") == "success":
                continue  # 새로 만든 success 리스트 사용
            # rejected/untried 중 이번 fallback에서 성공한 slot은 제외
            if r.get("id") in success_keys:
                continue
            rp_status.append(r)

        state["ref_point_status"] = rp_status
        with open(_os.path.join(_dd, "ref_point_status.json"), "w", encoding="utf-8") as _f:
            _json.dump({
                "total_points": len(rp_status),
                "success_count": sum(1 for r in rp_status if r["status"] == "success"),
                "rejected_count": sum(1 for r in rp_status if r["status"] == "rejected"),
                "untried_count": sum(1 for r in rp_status if r["status"] == "untried"),
                "ref_points": rp_status,
            }, _f, ensure_ascii=False, indent=2)
    except Exception as _e:
        logger.warning(f"[place:small] ref_point_status 재덤프 실패: {_e}")
