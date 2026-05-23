"""
Stage 4: HDD 무결성 검사 (매주 일요일 새벽 3시)
distributor.py가 기록한 SHA-256 manifest를 재계산하여 비교.
"""
import hashlib
import json
import os

from config import CAMERA_HDD_MAP, CAMERA_PREFIX_MAP, ERRORS_DIR, MANIFEST_FILENAME
from notifier import notify


def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _count_errors_dir() -> int:
    if not os.path.isdir(ERRORS_DIR):
        return 0
    return sum(1 for _, _, fs in os.walk(ERRORS_DIR) for _ in fs)


def _check_hdd(hdd_root: str) -> tuple[int, list[str]]:
    """manifest 기준으로 HDD 무결성 검사. (정상 파일 수, 오류 목록) 반환."""
    manifest_path = os.path.join(hdd_root, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        return 0, [f"manifest 없음 (아직 배포된 적 없거나 경로 오류): {manifest_path}"]

    with open(manifest_path) as f:
        manifest: dict[str, str] = json.load(f)

    errors = []
    ok = 0
    for rel_path, expected in manifest.items():
        abs_path = os.path.join(hdd_root, rel_path)
        if not os.path.isfile(abs_path):
            errors.append(f"파일 없음: {rel_path}")
            continue
        if _sha256(abs_path) != expected:
            errors.append(f"체크섬 불일치: {rel_path}")
        else:
            ok += 1
    return ok, errors


def run_integrity_check():
    """CAMERA_HDD_MAP에 등록된 모든 HDD 검사."""
    all_hdds: set[str] = {hdd for lst in CAMERA_HDD_MAP.values() for hdd in lst}
    all_hdds |= {hdd for _, lst in CAMERA_PREFIX_MAP for hdd in lst}

    if not all_hdds:
        print("[검사] CAMERA_HDD_MAP이 비어있습니다.")
        return

    total_ok = 0
    all_errors: list[str] = []

    for hdd in sorted(all_hdds):
        if not os.path.isdir(hdd):
            msg = f"HDD 미연결: {hdd}"
            print(f"  [건너뜀] {msg}")
            all_errors.append(msg)
            continue

        print(f"  검사 중: {hdd} ...", end=" ", flush=True)
        ok, errors = _check_hdd(hdd)
        total_ok += ok
        all_errors.extend(f"[{hdd}] {e}" for e in errors)
        status = f"{ok}개 정상" + (f", {len(errors)}개 오류" if errors else "")
        print(status)

    errors_dir_count = _count_errors_dir()
    if errors_dir_count:
        all_errors.append(f"ERRORS_DIR 미처리 파일 {errors_dir_count}개 ({ERRORS_DIR})")

    if all_errors:
        preview = "\n".join(all_errors[:20])
        if len(all_errors) > 20:
            preview += f"\n... 외 {len(all_errors) - 20}개"
        print(f"\n[무결성 오류]\n{preview}")
        notify(
            "🚨 HDD 오류 발견",
            f"{len(all_errors)}건 발견\n{preview}",
            priority="high",
            tags=["warning"],
        )
    else:
        print(f"\n[검사 완료] {total_ok:,}장 이상 없음.")
        notify(
            "✅ 무결성 검사 통과",
            f"총 {total_ok:,}장 이상 없음",
            tags=["white_check_mark"],
        )
