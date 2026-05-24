"""
Stage 3: NVMe sorted/ → 카메라 기종별 HDD 배포 (새벽 4시 실행)
- Pass 1: 첫 번째 HDD 복사 + SHA-256 검증 → 알림
- Pass 2: 두 번째 HDD 복사 + 원본 대비 전체 교차 검증 → 백업 완료 알림
- 모든 HDD 검증 성공 후 NVMe 원본 삭제
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import tqdm

from config import (
    CAMERA_HDD_MAP, CAMERA_PREFIX_MAP, MANIFEST_FILENAME,
    SORTED_DIR, SORTED_WARN_FREE_GB, SUPPORTED_EXTENSIONS,
    VIDEO_EXTENSIONS, VIDEO_SORTED_DIR, VIDEO_SSD_LIST,
)
from notifier import notify


def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _unmount_hdd(mount_point: str) -> bool:
    """드라이브 안전 분리(unmount + power-off). 성공 시 True 반환."""
    try:
        r = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", mount_point],
            capture_output=True, text=True, timeout=5,
        )
        device = r.stdout.strip()
        if not device:
            print(f"  [언마운트] {os.path.basename(mount_point)}: 마운트 정보 없음")
            return False

        r = subprocess.run(
            ["udisksctl", "unmount", "-b", device, "--no-user-interaction"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            print(f"  [언마운트 실패] {os.path.basename(mount_point)}: {r.stderr.strip()}")
            return False

        # 물리 드라이브 스핀다운
        parent = device.rstrip("0123456789")
        subprocess.run(
            ["udisksctl", "power-off", "-b", parent, "--no-user-interaction"],
            capture_output=True, timeout=10,
        )
        print(f"  [안전 제거] {os.path.basename(mount_point)} ({device})")
        return True
    except Exception as e:
        print(f"  [언마운트 오류] {os.path.basename(mount_point)}: {e}")
        return False


def _read_sidecar(path: str) -> str | None:
    """path.sha256 사이드카에서 해시 읽기. 없으면 None."""
    try:
        with open(path + ".sha256") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _prune_manifest(hdd_root: str, manifest: dict) -> int:
    """HDD에 실제로 없는 파일의 manifest 항목 제거. 제거된 수 반환."""
    stale = [rel for rel in list(manifest) if not os.path.isfile(os.path.join(hdd_root, rel))]
    for rel in stale:
        del manifest[rel]
    return len(stale)


def _load_manifest(hdd_root: str) -> dict:
    """manifest 로드. 구형 문자열 포맷은 자동 마이그레이션."""
    path = os.path.join(hdd_root, MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        raw = json.load(f)
    result = {}
    for k, v in raw.items():
        if isinstance(v, str):
            result[k] = {"sha256": v, "size": None}
        elif isinstance(v, dict):
            result[k] = {"sha256": v.get("sha256"), "size": v.get("size")}
        else:
            result[k] = v
    return result


def _save_manifest(hdd_root: str, manifest: dict):
    path = os.path.join(hdd_root, MANIFEST_FILENAME)
    tmp = path + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # POSIX 원자적 교체 — 중간 크래시 시 기존 파일 보존


def _copy_to_hdd(src: str, hdd_root: str, rel_path: str, manifest: dict,
                 known_hash: str | None = None) -> bool:
    """
    src → hdd_root/rel_path 복사. 이미 존재하면 True(중복 및 스킵) 반환.
    복사 후 SHA-256 검증 수행. 실패 시(디스크 풀·불일치 등) dst 삭제 후 예외 발생.
    known_hash: 사이드카에서 미리 읽은 해시. 없으면 src를 직접 계산.
    """
    dst = os.path.join(hdd_root, rel_path)
    if os.path.isfile(dst):
        return True

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    src_hash = known_hash if known_hash else _sha256(src)
    try:
        shutil.copy2(src, dst)
        dst_hash = _sha256(dst)
        if src_hash != dst_hash:
            raise RuntimeError(f"복사 검증 실패 (SHA-256 불일치): {rel_path}")
    except Exception:
        try:
            os.remove(dst)
        except FileNotFoundError:
            pass
        raise

    manifest[rel_path] = {"sha256": src_hash, "size": os.path.getsize(dst)}
    return False


def _get_hdds_for_camera(camera: str) -> list[str] | None:
    if camera in CAMERA_HDD_MAP:
        return CAMERA_HDD_MAP[camera]
    upper = camera.upper()
    for prefix, hdd_list in CAMERA_PREFIX_MAP:
        if upper.startswith(prefix.upper()):
            return hdd_list
    return None


def _remove_empty_dirs(root: str):
    for dirpath, _, _ in os.walk(root, topdown=False):
        if dirpath != root and not os.listdir(dirpath):
            os.rmdir(dirpath)


def _date_range(dates: set[str]) -> str:
    valid = sorted(d for d in dates if d and not d.startswith("0000"))
    if not valid:
        return ""
    lo, hi = valid[0], valid[-1]
    return lo if lo == hi else f"{lo} ~ {hi}"


def distribute():
    """sorted/ 내 파일을 2패스로 HDD 배포."""
    free_gb = shutil.disk_usage(SORTED_DIR).free / 1024 ** 3
    if free_gb < SORTED_WARN_FREE_GB:
        notify(
            "⚠️ NVMe 여유 공간 부족",
            f"여유: {free_gb:.1f} GB (임계값: {SORTED_WARN_FREE_GB} GB)\nsorted/ 누적 확인 필요",
            priority="high",
            tags=["warning"],
        )

    candidates = [
        (dirpath, f)
        for dirpath, _, filenames in os.walk(SORTED_DIR)
        for f in filenames
        if os.path.splitext(f)[-1].lower() in SUPPORTED_EXTENSIONS
    ]

    if not candidates:
        print("[배포] sorted/ 비어있음.")
        return

    # ── Job 목록 ───────────────────────────────────────────────────────────────
    jobs: list[tuple[str, str, list[str]]] = []  # (src, rel, hdd_list)
    skipped_cameras: set[str] = set()
    all_dates: set[str] = set()  # rel 경로의 YYYY-MM-DD 폴더명

    for dirpath, filename in candidates:
        src = os.path.join(dirpath, filename)
        rel = os.path.relpath(src, SORTED_DIR)
        parts = Path(rel).parts
        camera = parts[0]
        if len(parts) >= 3:
            all_dates.add(parts[2])  # Camera/Year/YYYY-MM-DD/file
        hdd_list = _get_hdds_for_camera(camera)
        if hdd_list:
            jobs.append((src, rel, hdd_list))
        else:
            skipped_cameras.add(camera)

    if skipped_cameras:
        print(f"  [경고] HDD 매핑 없는 기종 (config.py 확인): {', '.join(sorted(skipped_cameras))}")

    if not jobs:
        return

    # ── 용량 사전 확인 ─────────────────────────────────────────────────────
    _need_map: dict[str, int] = {}
    for src, rel, hdd_list in jobs:
        try:
            sz = os.path.getsize(src)
        except OSError:
            continue
        for hdd in hdd_list:
            if os.path.isdir(hdd) and not os.path.isfile(os.path.join(hdd, rel)):
                _need_map[hdd] = _need_map.get(hdd, 0) + sz
    _insufficient: list[str] = []
    for hdd in sorted(_need_map):
        if not os.path.isdir(hdd):
            continue
        free = shutil.disk_usage(hdd).free / 1024 ** 3
        need = _need_map[hdd] / 1024 ** 3
        print(f"  [용량] {os.path.basename(hdd)}: 여유 {free:.1f} GB / 필요 {need:.1f} GB")
        if free < need:
            _insufficient.append(f"{os.path.basename(hdd)}: 여유 {free:.1f} GB / 필요 {need:.1f} GB")
    if _insufficient:
        notify("⚠️ HDD 용량 부족", "\n".join(_insufficient), priority="high", tags=["warning"])

    manifests: dict[str, dict] = {}
    multi_jobs = [(s, r, hl) for s, r, hl in jobs if len(hl) > 1]
    single_jobs = [(s, r, hl) for s, r, hl in jobs if len(hl) == 1]
    # 연결됐지만 오류가 발생한 HDD → 언마운트 대상에서 제외
    _hdd_errors: set[str] = set()

    # 사이드카 해시 선독: 배포 중 src를 여러 번 읽지 않도록
    sidecar_hashes: dict[str, str | None] = {rel: _read_sidecar(src) for src, rel, _ in jobs}

    # ── Pass 1: 첫 번째 HDD 복사 ───────────────────────────────────────────────
    p1_copied: dict[str, int] = {}  # hdd 표시명 -> 복사 수
    p1_dup = 0
    p1_errors: list[str] = []

    for src, rel, hdd_list in tqdm.tqdm(jobs, desc="1차 저장", disable=not sys.stdout.isatty()):
        hdd = hdd_list[0]
        if not os.path.isdir(hdd):
            p1_errors.append(f"HDD 미연결: {os.path.basename(hdd)}")
            continue
        if hdd not in manifests:
            manifests[hdd] = _load_manifest(hdd)
        try:
            is_dup = _copy_to_hdd(src, hdd, rel, manifests[hdd], known_hash=sidecar_hashes[rel])
            if is_dup:
                p1_dup += 1
            else:
                name = os.path.basename(hdd)
                p1_copied[name] = p1_copied.get(name, 0) + 1
        except Exception as e:
            p1_errors.append(f"{Path(rel).name}: {e}")
            _hdd_errors.add(hdd)

    for hdd, m in manifests.items():
        _save_manifest(hdd, m)

    # 1차 저장 알림
    date_str = _date_range(all_dates)
    hdd_line = "  ".join(f"{h}: {n}장" for h, n in sorted(p1_copied.items())) or "없음"
    p1_extras = []
    if p1_dup:
        p1_extras.append(f"중복 및 스킵 {p1_dup}건")
    if p1_errors:
        p1_extras.append(f"오류 {len(p1_errors)}건")
    p1_body = (f"{date_str}\n" if date_str else "") + hdd_line
    if p1_extras:
        p1_body += "\n" + "  ".join(p1_extras)
    title_p1 = "💾 1차 저장 완료" if multi_jobs else "💾 저장 완료"
    print(f"\n[1차 저장] {hdd_line}" + (f"  ({date_str})" if date_str else ""))
    notify(title_p1, p1_body, tags=["floppy_disk"])

    # 단일 HDD 원본 삭제
    for src, rel, hdd_list in single_jobs:
        if os.path.isfile(os.path.join(hdd_list[0], rel)) and os.path.isfile(src):
            os.remove(src)
            try:
                os.remove(src + ".sha256")
            except OSError:
                pass

    if not multi_jobs:
        _remove_empty_dirs(SORTED_DIR)
        pruned_total = 0
        for hdd, m in manifests.items():
            pruned = _prune_manifest(hdd, m)
            if pruned:
                pruned_total += pruned
                _save_manifest(hdd, m)
        if pruned_total:
            print(f"[배포] manifest 고아 항목 {pruned_total}개 정리됨")
        _do_unmount(manifests, _hdd_errors)
        return

    # ── Pass 2: 두 번째 HDD 복사 + 원본 대비 교차 검증 ────────────────────────
    p2_dup = 0
    verify_errors: list[str] = []
    # 검증 실패(SHA-256 불일치, HDD 미연결, 복사 오류)가 발생한 rel 경로.
    # 이 집합에 포함된 파일은 소스를 삭제하지 않는다.
    _unsafe_rels: set[str] = set()

    for src, rel, hdd_list in tqdm.tqdm(multi_jobs, desc="2차 저장 및 검증", disable=not sys.stdout.isatty()):
        # 두 번째(이상) HDD에 복사
        for hdd in hdd_list[1:]:
            if not os.path.isdir(hdd):
                verify_errors.append(f"HDD 미연결: {os.path.basename(hdd)}")
                _unsafe_rels.add(rel)
                continue
            if hdd not in manifests:
                manifests[hdd] = _load_manifest(hdd)
            try:
                is_dup = _copy_to_hdd(src, hdd, rel, manifests[hdd], known_hash=sidecar_hashes[rel])
                if is_dup:
                    p2_dup += 1
            except Exception as e:
                verify_errors.append(f"{Path(rel).name}: {e}")
                _unsafe_rels.add(rel)
                _hdd_errors.add(hdd)

        # 사이드카 해시(없으면 src 직접 계산)로 전체 HDD 교차 검증
        if os.path.isfile(src):
            src_hash = sidecar_hashes[rel] or _sha256(src)
            for hdd in hdd_list:
                dst = os.path.join(hdd, rel)
                if not os.path.isfile(dst):
                    _unsafe_rels.add(rel)
                    if os.path.isdir(hdd):
                        _hdd_errors.add(hdd)
                elif _sha256(dst) != src_hash:
                    verify_errors.append(
                        f"교차검증 실패: {Path(rel).name} ({os.path.basename(hdd)})"
                    )
                    _unsafe_rels.add(rel)
                    _hdd_errors.add(hdd)

    for hdd, m in manifests.items():
        _save_manifest(hdd, m)

    # 모든 HDD에 SHA-256 검증이 완료된 파일만 소스 삭제
    backup_count = 0
    for src, rel, hdd_list in multi_jobs:
        if rel in _unsafe_rels:
            continue  # 검증 실패 또는 HDD 미연결 → 소스 보존
        all_present = all(os.path.isfile(os.path.join(hdd, rel)) for hdd in hdd_list)
        if all_present and os.path.isfile(src):
            os.remove(src)
            try:
                os.remove(src + ".sha256")
            except OSError:
                pass
            backup_count += 1

    _remove_empty_dirs(SORTED_DIR)

    # ── manifest 정리 (HDD에 없는 고아 항목 제거) ─────────────────────────────
    pruned_total = 0
    for hdd, m in manifests.items():
        pruned = _prune_manifest(hdd, m)
        if pruned:
            pruned_total += pruned
            _save_manifest(hdd, m)
    if pruned_total:
        print(f"[배포] manifest 고아 항목 {pruned_total}개 정리됨")

    # 백업 완료 알림
    all_hdds = sorted({hdd for _, _, hl in multi_jobs for hdd in hl})
    hdd_checks = "  ".join(
        f"{os.path.basename(h)} ✓" if os.path.isdir(h) else f"{os.path.basename(h)} 미연결"
        for h in all_hdds
    )
    backup_body = (f"{date_str}\n" if date_str else "") + f"{hdd_checks}\n총 {backup_count}장 백업 완료"
    if p2_dup:
        backup_body += f"  ·  중복 및 스킵 {p2_dup}건"
    if verify_errors:
        preview = "\n".join(verify_errors[:5])
        if len(verify_errors) > 5:
            preview += f"\n... 외 {len(verify_errors) - 5}건"
        backup_body += f"\n오류 {len(verify_errors)}건\n{preview}"

    _free_lines = "\n".join(
        f"{os.path.basename(h)}: {shutil.disk_usage(h).free / 1024**3:.1f} GB 남음"
        for h in sorted(manifests) if os.path.isdir(h)
    )
    if _free_lines:
        backup_body += "\n" + _free_lines

    has_errors = bool(verify_errors)
    title_p2 = "⚠️ 백업 오류" if has_errors else "✅ 백업 완료"
    priority = "high" if has_errors else "default"
    tag = "warning" if has_errors else "white_check_mark"

    print(f"\n[백업 완료] {hdd_checks} | {backup_count}장")
    if verify_errors:
        for e in verify_errors[:3]:
            print(f"  [검증 오류] {e}")

    notify(title_p2, backup_body, priority=priority, tags=[tag])

    _do_unmount(manifests, _hdd_errors)


def _do_unmount(manifests: dict, hdd_errors: set[str]):
    """오류 없이 완료된 HDD만 안전 분리."""
    safe = sorted(set(manifests) - hdd_errors)
    if not safe:
        return
    unmounted = [os.path.basename(h) for h in safe if _unmount_hdd(h)]
    if unmounted:
        notify("💿 HDD 안전 제거 완료", "  ".join(unmounted), tags=["eject_button"])


def distribute_videos():
    """video_sorted/ 내 영상을 VIDEO_SSD_LIST 모든 SSD에 배포."""
    if not VIDEO_SSD_LIST:
        return

    candidates = [
        os.path.join(dp, f)
        for dp, _, files in os.walk(VIDEO_SORTED_DIR)
        for f in files
        if os.path.splitext(f)[-1].lower() in VIDEO_EXTENSIONS
    ]

    if not candidates:
        print("[영상 배포] video_sorted/ 비어있음.")
        return

    manifests: dict[str, dict] = {}
    _ssd_errors: set[str] = set()
    _ssd_missing: set[str] = set()  # 미연결 오류는 SSD당 1회만 기록
    errors: list[str] = []
    unsafe_rels: set[str] = set()
    all_dates: set[str] = set()

    # 사이드카 해시 선독
    sidecar_hashes: dict[str, str | None] = {
        os.path.relpath(src, VIDEO_SORTED_DIR): _read_sidecar(src) for src in candidates
    }

    for src in tqdm.tqdm(candidates, desc="영상 배포", disable=not sys.stdout.isatty()):
        rel = os.path.relpath(src, VIDEO_SORTED_DIR)
        parts = Path(rel).parts
        if len(parts) >= 2:
            all_dates.add(parts[1])  # Year/YYYY-MM-DD/file → parts[1]

        if not os.path.isfile(src):
            continue
        known_hash = sidecar_hashes[rel]

        for ssd in VIDEO_SSD_LIST:
            if not os.path.isdir(ssd):
                if ssd not in _ssd_missing:
                    errors.append(f"SSD 미연결: {os.path.basename(ssd)}")
                    _ssd_missing.add(ssd)
                unsafe_rels.add(rel)
                continue
            if ssd not in manifests:
                manifests[ssd] = _load_manifest(ssd)
            try:
                _copy_to_hdd(src, ssd, rel, manifests[ssd], known_hash=known_hash)
            except Exception as e:
                errors.append(f"{Path(rel).name}: {e}")
                unsafe_rels.add(rel)
                _ssd_errors.add(ssd)

        # 사이드카 해시로 교차 검증
        src_hash = known_hash or _sha256(src)
        for ssd in VIDEO_SSD_LIST:
            dst = os.path.join(ssd, rel)
            if not os.path.isfile(dst):
                unsafe_rels.add(rel)
                if os.path.isdir(ssd):
                    _ssd_errors.add(ssd)
            elif _sha256(dst) != src_hash:
                errors.append(f"교차검증 실패: {Path(rel).name} ({os.path.basename(ssd)})")
                unsafe_rels.add(rel)
                _ssd_errors.add(ssd)

    for ssd, m in manifests.items():
        _save_manifest(ssd, m)

    # 모든 SSD 검증 완료된 파일만 소스 삭제
    saved = 0
    for src in candidates:
        rel = os.path.relpath(src, VIDEO_SORTED_DIR)
        if rel in unsafe_rels:
            continue
        all_present = all(os.path.isfile(os.path.join(ssd, rel)) for ssd in VIDEO_SSD_LIST)
        if all_present and os.path.isfile(src):
            os.remove(src)
            try:
                os.remove(src + ".sha256")
            except OSError:
                pass
            saved += 1

    _remove_empty_dirs(VIDEO_SORTED_DIR)

    for ssd, m in manifests.items():
        pruned = _prune_manifest(ssd, m)
        if pruned:
            _save_manifest(ssd, m)

    date_str = _date_range(all_dates)
    body = (f"{date_str}\n" if date_str else "") + f"총 {saved}개 저장 완료"
    if errors:
        preview = "\n".join(errors[:5])
        body += f"\n오류 {len(errors)}건\n{preview}"
    has_errors = bool(errors)
    print(f"\n[영상 배포] {saved}개" + (f"  ({date_str})" if date_str else ""))
    notify(
        "⚠️ 영상 배포 오류" if has_errors else "🎬 영상 배포 완료",
        body,
        priority="high" if has_errors else "default",
        tags=["warning" if has_errors else "clapper"],
    )
