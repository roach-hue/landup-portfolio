"""GLB 바이트 → 디스크 저장 공용 모듈.

소형·대형 파이프라인의 glb_exporter 노드가 공통으로 호출.
- 저장 루트: {backend}/storage/glb/
- 파일명: {uuid4}.glb — 충돌 불가
- 반환값: 'storage/glb/{uuid}.glb' 상대경로 (backend 디렉토리 기준)

디버그:
- 저장 호출마다 debug_logs/YYYY-MM-DD/ 에 'glb_storage_save.json' 덤프
  (입력 bytes 길이, 파일명, 절대/상대 경로, 기록 후 재검증 결과, 에러)

Java 측은 자기 backend 디렉토리 + 이 상대경로로 join 해서 파일 스트리밍.
MVP (b) 방식 — 프로덕션 전환 시 key-only (a) 로 2줄 변경 + DB UPDATE 1회.
"""
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/ 디렉토리 — app/storage/glb_storage.py 기준 parents[3]
#   parents[0]=storage, [1]=app, [2]=python, [3]=backend, [4]=project root
_BACKEND_DIR = Path(__file__).resolve().parents[3]
_STORAGE_DIR = _BACKEND_DIR / "storage" / "glb"


def save_glb_bytes(glb_bytes: bytes) -> str:
    """GLB 바이트를 파일로 저장하고 backend 기준 상대경로를 반환.

    Args:
        glb_bytes: trimesh Scene.export(file_type='glb') 결과 바이너리.

    Returns:
        상대경로 문자열 'storage/glb/{uuid}.glb' (backend 디렉토리 기준).

    Raises:
        ValueError: glb_bytes 가 비어있을 때.
        OSError: 디스크 쓰기 실패 시.
    """
    if not glb_bytes:
        raise ValueError("glb_bytes is empty")

    _STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.glb"
    file_path = _STORAGE_DIR / filename
    relative = f"storage/glb/{filename}"

    error: str | None = None
    try:
        file_path.write_bytes(bytes(glb_bytes))
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        _dump_save(glb_bytes, filename, relative, file_path, error)
        raise

    _dump_save(glb_bytes, filename, relative, file_path, None)
    logger.info(f"[glb_storage] saved {len(glb_bytes)} bytes → {relative}")
    return relative


def _dump_save(
    glb_bytes: bytes,
    filename: str,
    relative: str,
    file_path: Path,
    error: str | None,
) -> None:
    """저장 시도 결과를 debug_logs 에 JSON 덤프. 덤프 실패가 저장 로직에 영향 주지 않도록 격리."""
    try:
        from app.debug import dump_debug
        actual_size = file_path.stat().st_size if file_path.exists() else 0
        dump_debug("glb_storage_save.json", {
            "input": {
                "bytes_len": len(glb_bytes) if glb_bytes else 0,
                "first_16_hex": bytes(glb_bytes[:16]).hex() if glb_bytes else None,
            },
            "output": {
                "filename": filename,
                "relative_path": relative,
                "absolute_path": str(file_path),
            },
            "verification": {
                "file_exists": file_path.exists(),
                "file_size_bytes": actual_size,
                "size_match": actual_size == len(glb_bytes) if glb_bytes else False,
            },
            "error": error,
        })
    except Exception as e:
        logger.warning(f"[glb_storage] dump failed: {e}")
