"""
Stage 2: NVMe inbox/ → sorted/Camera/Year/YYYY-MM-DD/
중복(같은 경로·같은 크기) → 삭제.
이름 충돌이지만 크기 다름(시퀀스 번호 롤오버 등) → 새 이름으로 저장.
EXIF 오류 파일 → ERRORS_DIR 격리.
"""
import os
import shutil
import sys
import threading
from datetime import datetime

import exifread
import tqdm

_sort_lock = threading.Lock()

from config import (
    CAMERA_NAME_OVERRIDES,
    ERRORS_DIR, INBOX_DIR, JPG_SORTED_DIR, SORTED_DIR,
    SUPPORTED_EXTENSIONS, JPG_EXTENSIONS, VIDEO_EXTENSIONS, VIDEO_SORTED_DIR,
)
from notifier import notify


def _normalize_camera(tag: dict) -> str:
    """
    EXIF Make + Model → 정규화된 카메라명.
    Make의 첫 단어가 Model에 없으면 앞에 붙임.
      "LEICA CAMERA AG" + "X2"      → "LEICA X2"
      "LEICA CAMERA AG" + "LEICA M10" → "LEICA M10"
      "NIKON CORPORATION" + "NIKON D850" → "NIKON D850"
    """
    make  = str(tag.get("Image Make", "")).strip()
    model = str(tag.get("Image Model", "Misc")).strip() or "Misc"
    if make:
        brand = make.split()[0]
        if brand.upper() not in model.upper():
            model = f"{brand} {model}"
    return CAMERA_NAME_OVERRIDES.get(model, model)


def _get_video_dest_dir(filepath: str) -> str:
    """파일 수정 시각 기반으로 VIDEO_SORTED_DIR 내 목적지 디렉터리 반환."""
    dt = datetime.fromtimestamp(os.path.getmtime(filepath))
    y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
    return os.path.join(VIDEO_SORTED_DIR, y, f"{y}-{m}-{d}")


def _get_dest_dir(filepath: str, base_dir: str = SORTED_DIR) -> str:
    """EXIF 기반으로 base_dir 내 목적지 디렉터리 반환."""
    with open(filepath, 'rb') as f:
        # stop_tag: Make/Model은 IFD0에서 먼저 읽힘 → DateTimeOriginal 발견 시 중단해도 OK
        tag = exifread.process_file(f, stop_tag='EXIF DateTimeOriginal')

    camera = _normalize_camera(tag)
    shoot_time = str(tag.get("EXIF DateTimeOriginal", "0000:00:00 00:00:00"))

    try:
        y, m, d = shoot_time.split(" ")[0].split(":")
    except (IndexError, ValueError):
        y, m, d = "0000", "00", "00"

    return os.path.join(base_dir, camera, y, f"{y}-{m}-{d}")


def _resolve_dest(dst_dir: str, filename: str, src: str) -> tuple[str, bool]:
    """
    목적지 경로와 중복 여부를 반환.
    - 없음: (dst_dir/filename, False)
    - 같은 크기(진짜 중복): (dst_dir/filename, True)
    - 다른 크기(이름 충돌): (dst_dir/stem_1.ext, False) 식으로 새 이름 부여
    """
    dst = os.path.join(dst_dir, filename)
    if not os.path.isfile(dst):
        return dst, False

    if os.path.getsize(src) == os.path.getsize(dst):
        return dst, True  # 진짜 중복 → 삭제해도 됨

    # 같은 날짜에 시퀀스 번호가 리셋된 다른 사진 → 이름 변경 후 보존
    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_dst = os.path.join(dst_dir, f"{stem}_{counter}{ext}")
        if not os.path.isfile(new_dst):
            return new_dst, False
        counter += 1


def _move_sidecar(src: str, dst: str):
    s = src + ".sha256"
    if os.path.isfile(s):
        try:
            shutil.move(s, dst + ".sha256")
        except Exception:
            pass


def _remove_sidecar(src: str):
    s = src + ".sha256"
    if os.path.isfile(s):
        try:
            os.remove(s)
        except Exception:
            pass


def _purge_orphan_sidecars(root: str):
    """대응하는 원본 파일 없는 .sha256 사이드카 삭제."""
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith(".sha256"):
                main = os.path.join(dirpath, f[:-7])
                if not os.path.isfile(main):
                    try:
                        os.remove(os.path.join(dirpath, f))
                    except Exception:
                        pass


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


def sort_inbox():
    """inbox/ 전체를 스캔하여 sorted/ 로 분류."""
    if not _sort_lock.acquire(blocking=False):
        print("[분류] 이미 실행 중. 건너뜀.")
        return
    try:
        _sort_inbox_inner()
    finally:
        _sort_lock.release()


def _sort_inbox_inner():
    _all_ext = SUPPORTED_EXTENSIONS + VIDEO_EXTENSIONS
    candidates = [
        (dirpath, f)
        for dirpath, _, filenames in os.walk(INBOX_DIR)
        for f in filenames
        if os.path.splitext(f)[-1].lower() in _all_ext
    ]

    if not candidates:
        print("[분류] inbox 비어있음.")
        return

    counts = {"sorted": 0, "renamed": 0, "duplicate": 0, "error": 0}
    dates: set[str] = set()

    for dirpath, filename in tqdm.tqdm(candidates, desc="분류 중", disable=not sys.stdout.isatty()):
        src = os.path.join(dirpath, filename)
        ext = os.path.splitext(filename)[-1].lower()
        try:
            if ext in VIDEO_EXTENSIONS:
                dst_dir = _get_video_dest_dir(src)
            elif ext in JPG_EXTENSIONS:
                dst_dir = _get_dest_dir(src, JPG_SORTED_DIR)
            else:
                dst_dir = _get_dest_dir(src)
            dates.add(os.path.basename(dst_dir))  # YYYY-MM-DD
            os.makedirs(dst_dir, exist_ok=True)
            dst, is_dup = _resolve_dest(dst_dir, filename, src)

            if is_dup:
                os.remove(src)
                _remove_sidecar(src)
                counts["duplicate"] += 1
            else:
                shutil.move(src, dst)
                _move_sidecar(src, dst)
                if os.path.basename(dst) != filename:
                    counts["renamed"] += 1
                    print(f"  [이름변경] {filename} → {os.path.basename(dst)}")
                else:
                    counts["sorted"] += 1

        except Exception as e:
            counts["error"] += 1
            print(f"  [오류→격리] {filename}: {e}")
            try:
                os.makedirs(ERRORS_DIR, exist_ok=True)
                err_dst = os.path.join(ERRORS_DIR, filename)
                if os.path.exists(err_dst):
                    stem, ext = os.path.splitext(filename)
                    i = 1
                    while os.path.exists(err_dst):
                        err_dst = os.path.join(ERRORS_DIR, f"{stem}_{i}{ext}")
                        i += 1
                shutil.move(src, err_dst)
            except Exception:
                pass  # 격리도 실패하면 원위치 유지

    _remove_empty_dirs(INBOX_DIR)
    _purge_orphan_sidecars(INBOX_DIR)

    total = sum(counts.values())
    date_str = _date_range(dates)
    stat = f"분류 {counts['sorted']}  이름변경 {counts['renamed']}  중복 및 스킵 {counts['duplicate']}"
    if counts['error']:
        stat += f"  오류 {counts['error']}"
    body = f"{total}장  {date_str}\n{stat}" if date_str else f"{total}장\n{stat}"
    print(f"\n[분류 완료] {total}장 ({date_str}): 분류 {counts['sorted']} / 이름변경 {counts['renamed']} / 중복 및 스킵 {counts['duplicate']} / 오류 {counts['error']}")
    notify("🗂 분류 완료", body, tags=["card_file_box"])
