"""디버그 좌표 덤프 유틸 — debug_logs/YYYY-MM-DD/ 폴더에 JSON 저장."""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def dump_debug(filename: str, data: dict) -> None:
    """디버그 좌표 덤프 → debug_logs/YYYY-MM-DD/ 날짜별 폴더. 시간 prefix + latest 덮어쓰기 병행."""
    now = datetime.now()
    date_dir = now.strftime("%Y-%m-%d")
    base_dir = os.path.join(os.path.dirname(__file__), "..", "debug_logs", date_dir)
    os.makedirs(base_dir, exist_ok=True)

    ts = now.strftime("%Y-%m-%d_%H-%M-%S")
    name, ext = os.path.splitext(filename)
    timestamped = f"{ts}_{name}{ext}"

    path_ts = os.path.join(base_dir, timestamped)
    with open(path_ts, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    # 최신 파일도 날짜 폴더에 덮어쓰기 (빠른 확인용)
    path_latest = os.path.join(base_dir, filename)
    with open(path_latest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"[debug] 덤프 저장: {date_dir}/{timestamped}")
