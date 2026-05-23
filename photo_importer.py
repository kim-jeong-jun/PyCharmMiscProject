# -----------------------------------------------------------------------------
# Copyright (c) 2019, Jeong-Jun Kim. All Rights Reserved.
# -----------------------------------------------------------------------------

import os
import shutil
import time
import exifread
import tqdm
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── 설정 ──────────────────────────────────────────────────────────────────────
To = ""   # TODO: 하드디스크 경로 입력 (예: "/media/jjkim/MyHDD/Photos")

WATCH_DIRS = [
    "/media",
    f"/run/media/{os.getenv('USER', '')}",
]
SUPPORTED_EXTENSIONS = ('.nef', '.dng', '.jpg', '.jpeg')
MOUNT_SETTLE_DELAY = 3  # 카드 마운트 후 읽기 시작까지 대기 (초)
# ─────────────────────────────────────────────────────────────────────────────


def get_dest_dir(filepath):
    """EXIF 기반 목적지 경로 반환: To/Camera/Year/YYYY-MM-DD"""
    with open(filepath, 'rb') as f:
        tag = exifread.process_file(f, stop_tag='EXIF DateTimeOriginal')

    camera = str(tag.get("Image Model", "Misc")).strip() or "Misc"
    shoot_time = str(tag.get("EXIF DateTimeOriginal", "0000:00:00 00:00:00"))

    try:
        y, m, d = shoot_time.split(" ")[0].split(":")
    except (IndexError, ValueError):
        y, m, d = "0000", "00", "00"

    return os.path.join(To, camera, y, f"{y}-{m}-{d}")


def copy_file(src_path, filename):
    """
    단일 파일을 EXIF 경로로 복사.
    - 정상: To/Camera/Year/YYYY-MM-DD/filename
    - 1차 중복: 위 경로/Redundant/filename
    - 2차 중복: 무시
    반환값: "sorted" | "overlap" | "neglect" | raises
    """
    dst_dir = get_dest_dir(src_path)
    dst_path = os.path.join(dst_dir, filename)
    redundant_dir = os.path.join(dst_dir, "Redundant")
    redundant_path = os.path.join(redundant_dir, filename)

    os.makedirs(dst_dir, exist_ok=True)

    if not os.path.isfile(dst_path):
        shutil.copy2(src_path, dst_path)
        return "sorted"

    if os.path.isfile(redundant_path):
        return "neglect"

    os.makedirs(redundant_dir, exist_ok=True)
    shutil.copy2(src_path, redundant_path)
    return "overlap"


def process_card(mount_point):
    """마운트된 카드 전체를 스캔하여 하드디스크로 복사."""
    if not To:
        print("[오류] To 경로가 설정되지 않았습니다. 코드 상단의 To 변수를 설정해주세요.")
        return

    print(f"\n카드 감지: {mount_point}")
    print(f"  → {MOUNT_SETTLE_DELAY}초 대기 후 시작...")
    time.sleep(MOUNT_SETTLE_DELAY)

    to_sort = [
        (dirpath, f)
        for dirpath, _, filenames in os.walk(mount_point)
        for f in filenames
        if os.path.splitext(f)[-1].lower() in SUPPORTED_EXTENSIONS
    ]

    if not to_sort:
        print("  사진 파일 없음. 건너뜀.")
        return

    counts = {"sorted": 0, "overlap": 0, "neglect": 0, "error": 0}
    start = time.time()

    for dirpath, filename in tqdm.tqdm(to_sort, desc="복사 중"):
        try:
            result = copy_file(os.path.join(dirpath, filename), filename)
            counts[result] += 1
        except Exception as e:
            counts["error"] += 1
            tqdm.tqdm.write(f"  [오류] {filename}: {e}")

    elapsed = time.strftime('%H:%M:%S', time.gmtime(int(time.time() - start)))
    total = sum(counts.values())
    print(f"\n완료: 총 {total}개")
    print(f"  복사됨    : {counts['sorted']}개")
    print(f"  Redundant : {counts['overlap']}개")
    print(f"  무시됨    : {counts['neglect']}개")
    print(f"  오류      : {counts['error']}개")
    print(f"  소요시간  : {elapsed}\n")


class MountWatcher(FileSystemEventHandler):
    """새 디렉터리 생성(= 카드 마운트) 감지 후 process_card 실행."""

    def on_created(self, event):
        if event.is_directory:
            process_card(event.src_path)


def main():
    observer = Observer()
    watched = 0
    for d in WATCH_DIRS:
        if os.path.isdir(d):
            observer.schedule(MountWatcher(), d, recursive=False)
            print(f"감시 중: {d}")
            watched += 1

    if watched == 0:
        print("[경고] 감시할 수 있는 마운트 디렉터리를 찾지 못했습니다.")
        print("  WATCH_DIRS를 확인해주세요.")
        return

    observer.start()
    print("SD/CF 카드를 연결하면 자동으로 복사를 시작합니다.  종료: Ctrl+C\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
