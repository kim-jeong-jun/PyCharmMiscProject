"""
Stage 4: HDD 무결성 검사 (매주 일요일 새벽 3시)
2패스:
  Pass 1 (빠름, 전수): 모든 파일 존재 + 크기 확인
  Pass 2 (회전식 SHA-256): 시간 예산 내에서 가장 오래전 검증된 파일부터 재계산
"""
import hashlib
import json
import os
import time
from datetime import datetime

from config import (
    CAMERA_HDD_MAP, CAMERA_PREFIX_MAP, DEEP_CHECK_BUDGET_SECONDS,
    ERRORS_DIR, MANIFEST_FILENAME,
)
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


def _load_manifest(hdd_root: str) -> dict:
    path = os.path.join(hdd_root, MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        raw = json.load(f)
    result = {}
    for k, v in raw.items():
        if isinstance(v, str):
            result[k] = {"sha256": v, "size": None, "verified": None}
        else:
            result[k] = v
    return result


def _save_manifest(hdd_root: str, manifest: dict):
    with open(os.path.join(hdd_root, MANIFEST_FILENAME), 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def _check_hdd(hdd_root: str) -> tuple[int, int, int, list[str]]:
    """
    2패스 무결성 검사.
    반환: (quick_ok, deep_ok, total_entries, errors)
    """
    manifest_path = os.path.join(hdd_root, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        return 0, 0, 0, [f"manifest 없음: {manifest_path}"]

    manifest = _load_manifest(hdd_root)
    if not manifest:
        return 0, 0, 0, []

    today = datetime.now().strftime("%Y-%m-%d")

    # 가장 오래전 검증된(또는 미검증) 항목부터 — Pass 2 순서 결정
    sorted_entries = sorted(
        manifest.items(),
        key=lambda kv: kv[1].get("verified") or "" if isinstance(kv[1], dict) else "",
    )

    errors: list[str] = []
    quick_ok = 0

    # ── Pass 1: 존재 + 크기 전수확인 ──────────────────────────────────────────
    stat_failed: set[str] = set()
    for rel, meta in sorted_entries:
        abs_path = os.path.join(hdd_root, rel)
        if not os.path.isfile(abs_path):
            errors.append(f"파일 없음: {rel}")
            stat_failed.add(rel)
            continue
        expected_size = meta.get("size") if isinstance(meta, dict) else None
        if expected_size is not None and os.path.getsize(abs_path) != expected_size:
            errors.append(f"크기 불일치: {rel}")
            stat_failed.add(rel)
            continue
        quick_ok += 1

    # ── Pass 2: 시간 예산 내 순환 SHA-256 ─────────────────────────────────────
    deep_ok = 0
    manifest_dirty = False
    budget_start = time.monotonic()

    for rel, meta in sorted_entries:
        if time.monotonic() - budget_start >= DEEP_CHECK_BUDGET_SECONDS:
            break
        if rel in stat_failed:
            continue

        abs_path = os.path.join(hdd_root, rel)
        expected_sha = meta.get("sha256") if isinstance(meta, dict) else meta
        if not expected_sha:
            continue

        actual = _sha256(abs_path)
        if actual != expected_sha:
            errors.append(f"체크섬 불일치: {rel}")
        else:
            deep_ok += 1
            if isinstance(manifest[rel], dict):
                manifest[rel]["verified"] = today
                manifest_dirty = True

    if manifest_dirty:
        _save_manifest(hdd_root, manifest)

    return quick_ok, deep_ok, len(manifest), errors


def run_integrity_check():
    """CAMERA_HDD_MAP에 등록된 모든 HDD 검사."""
    all_hdds: set[str] = {hdd for lst in CAMERA_HDD_MAP.values() for hdd in lst}
    all_hdds |= {hdd for _, lst in CAMERA_PREFIX_MAP for hdd in lst}

    if not all_hdds:
        print("[검사] CAMERA_HDD_MAP이 비어있습니다.")
        return

    total_quick = 0
    total_deep = 0
    total_entries = 0
    all_errors: list[str] = []

    for hdd in sorted(all_hdds):
        if not os.path.isdir(hdd):
            msg = f"HDD 미연결: {hdd}"
            print(f"  [건너뜀] {msg}")
            all_errors.append(msg)
            continue

        print(f"  검사 중: {os.path.basename(hdd)} ...", end=" ", flush=True)
        quick_ok, deep_ok, n_entries, errors = _check_hdd(hdd)
        total_quick += quick_ok
        total_deep += deep_ok
        total_entries += n_entries
        all_errors.extend(f"[{os.path.basename(hdd)}] {e}" for e in errors)
        status = f"전수확인 {quick_ok}/{n_entries}개 · SHA-256 {deep_ok}개"
        if errors:
            status += f" · 오류 {len(errors)}개"
        print(status)

    # 전체 커버 예상 주 수
    coverage_note = ""
    if total_deep > 0 and total_entries > 0:
        weeks = -(-total_entries // total_deep)  # ceiling division
        coverage_note = f"  (전체 커버 예상 {weeks}주)"

    errors_dir_count = _count_errors_dir()
    if errors_dir_count:
        all_errors.append(f"ERRORS_DIR 미처리 파일 {errors_dir_count}개 ({ERRORS_DIR})")

    summary = f"전수확인 {total_quick}개 OK / SHA-256 {total_deep}개{coverage_note}"

    if all_errors:
        preview = "\n".join(all_errors[:20])
        if len(all_errors) > 20:
            preview += f"\n... 외 {len(all_errors) - 20}개"
        print(f"\n[무결성 오류]\n{preview}")
        notify(
            "🚨 HDD 오류 발견",
            f"{len(all_errors)}건 발견\n{summary}\n{preview}",
            priority="high",
            tags=["warning"],
        )
    else:
        print(f"\n[검사 완료] {summary}")
        notify(
            "✅ 무결성 검사 통과",
            summary,
            tags=["white_check_mark"],
        )
