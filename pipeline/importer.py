"""
Stage 1: SD/CF 카드 감지 → NVMe inbox/ 복사 → sorter 자동 호출
         바탕화면 드롭 폴더 감시 → inbox/ 이동 → sorter 자동 호출
"""
import hashlib
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import sys

import tqdm
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import (
    DESKTOP_DROP_DIR, INBOX_DIR,
    MOUNT_SETTLE_DELAY, SUPPORTED_EXTENSIONS, VIDEO_EXTENSIONS, WATCH_DIRS,
)
from notifier import notify


_MIN_HDD_SIZE_BYTES = 500 * 1024 ** 3  # 500 GB


def _is_camera_card(mount_point: str) -> bool:
    """단일 파티션 500 GB 이상 USB 장치는 외장하드로 간주, 처리하지 않음."""
    try:
        r = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", mount_point],
            capture_output=True, text=True, timeout=5,
        )
        device = r.stdout.strip()
        if not device:
            return False
        parent = device.rstrip("0123456789")

        r = subprocess.run(
            ["lsblk", "-n", "-b", "-d", "-o", "TRAN,SIZE", parent],
            capture_output=True, text=True, timeout=5,
        )
        parts = r.stdout.split()
        if len(parts) < 2 or parts[0].lower() != "usb":
            return False
        size_bytes = int(parts[1])

        if size_bytes >= _MIN_HDD_SIZE_BYTES:
            return False
        return True
    except Exception:
        return False


def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


# ── 드롭 폴더 sort debounce ────────────────────────────────────────────────────
_sort_timer: threading.Timer | None = None
_sort_lock = threading.Lock()


def _schedule_sort(delay: float = 3.0):
    """마지막 파일 투입 후 delay초 뒤에 sort_inbox()를 한 번만 실행."""
    global _sort_timer
    with _sort_lock:
        if _sort_timer is not None:
            _sort_timer.cancel()
        from sorter import sort_inbox
        _sort_timer = threading.Timer(delay, sort_inbox)
        _sort_timer.daemon = True
        _sort_timer.start()


def copy_card_to_inbox(mount_point: str) -> int:
    """카드 내 사진 파일 전체를 inbox/{timestamp}_{card_name}/ 으로 복사."""
    card_name = Path(mount_point).name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_root = os.path.join(INBOX_DIR, f"{timestamp}_{card_name}")

    _all_ext = SUPPORTED_EXTENSIONS + VIDEO_EXTENSIONS
    candidates = [
        (dirpath, f)
        for dirpath, _, filenames in os.walk(mount_point)
        for f in filenames
        if os.path.splitext(f)[-1].lower() in _all_ext
    ]

    if not candidates:
        print(f"  [가져오기] 사진 없음: {mount_point}")
        return 0

    os.makedirs(dest_root, exist_ok=True)
    copied = 0
    for dirpath, filename in tqdm.tqdm(candidates, desc="가져오는 중", disable=not sys.stdout.isatty()):
        rel = os.path.relpath(dirpath, mount_point)
        dst_dir = os.path.join(dest_root, rel)
        os.makedirs(dst_dir, exist_ok=True)
        dst_file = os.path.join(dst_dir, filename)
        shutil.copy2(os.path.join(dirpath, filename), dst_file)
        try:
            with open(dst_file + ".sha256", "w") as sf:
                sf.write(_sha256(dst_file))
        except Exception as e:
            print(f"  [경고] 사이드카 쓰기 실패: {filename}: {e}")
        copied += 1

    print(f"  [가져오기] {copied}개 → {dest_root}")
    notify(
        "📥 카드 가져오기 완료",
        f"{card_name} — {copied}장 inbox 보관",
        tags=["inbox_tray"],
    )
    return copied


class _MountWatcher(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            return
        if not _is_camera_card(event.src_path):
            print(f"[무시] 카메라 카드 아님 (HDD/SSD): {event.src_path}")
            return
        print(f"\n[카드 감지] {event.src_path}")
        time.sleep(MOUNT_SETTLE_DELAY)
        try:
            n = copy_card_to_inbox(event.src_path)
            if n > 0:
                from sorter import sort_inbox
                sort_inbox()
        except Exception as e:
            # watchdog 스레드에서 예외가 묻히지 않도록 명시적으로 출력
            print(f"[오류] 카드 처리 중 예외 발생: {e}")


class _DropFolderWatcher(FileSystemEventHandler):
    """
    바탕화면 드롭 폴더 감시.

    cp로 복사할 때: inotify가 IN_CREATE → IN_CLOSE_WRITE 순으로 발동.
      on_created에서 타이머를 등록하지만, on_closed가 발동하면 타이머를 취소하고
      즉시 처리한다.

    mv로 이동할 때: inotify가 IN_MOVED_TO만 발동 → watchdog은 FileCreatedEvent로 매핑.
      on_created에서 2초 타이머 등록 후 처리. on_closed는 발동하지 않음.

    경로별로 타이머를 _timers 딕셔너리에 추적하여 동일 경로 중복 타이머를 방지한다.
    """

    def __init__(self):
        super().__init__()
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}
        self._timer_lock = threading.Lock()

    def on_closed(self, event):
        """IN_CLOSE_WRITE: cp 완료. 대기 중인 on_created 타이머 취소 후 즉시 처리."""
        if not event.is_directory:
            with self._timer_lock:
                t = self._timers.pop(event.src_path, None)
            if t:
                t.cancel()
            self._handle(event.src_path)

    def on_created(self, event):
        """IN_MOVED_TO(mv) 또는 cp 중간 이벤트. 경로별 타이머를 등록한다."""
        if not event.is_directory:
            path = event.src_path
            with self._timer_lock:
                old = self._timers.pop(path, None)
                if old:
                    old.cancel()
                t = threading.Timer(2.0, self._run_timer, args=(path,))
                t.daemon = True
                self._timers[path] = t
                t.start()

    def _run_timer(self, path: str):
        with self._timer_lock:
            self._timers.pop(path, None)
        self._handle(path)

    def _handle(self, path: str):
        ext = os.path.splitext(path)[-1].lower()
        if ext not in SUPPORTED_EXTENSIONS + VIDEO_EXTENSIONS:
            return
        with self._lock:
            if path in self._seen:
                return
            self._seen.add(path)
        try:
            if not os.path.isfile(path):
                return
            filename = os.path.basename(path)
            dest = os.path.join(INBOX_DIR, filename)
            if os.path.exists(dest):
                stem, ext = os.path.splitext(filename)
                i = 1
                while os.path.exists(dest):
                    dest = os.path.join(INBOX_DIR, f"{stem}_{i}{ext}")
                    i += 1
            shutil.move(path, dest)
            print(f"[드롭폴더] {filename} → inbox")
            _schedule_sort()
        except Exception as e:
            print(f"[오류] 드롭폴더 처리 실패: {e}")
        finally:
            with self._lock:
                self._seen.discard(path)


def start_watcher() -> Observer:
    observer = Observer()
    watched = 0
    for d in WATCH_DIRS:
        if os.path.isdir(d):
            observer.schedule(_MountWatcher(), d, recursive=False)
            print(f"감시 중: {d}")
            watched += 1
    if not watched:
        print("[경고] 감시 가능한 마운트 디렉터리 없음. WATCH_DIRS를 확인하세요.")

    os.makedirs(DESKTOP_DROP_DIR, exist_ok=True)
    observer.schedule(_DropFolderWatcher(), DESKTOP_DROP_DIR, recursive=False)
    print(f"드롭 폴더 감시 중: {DESKTOP_DROP_DIR}")

    observer.start()
    return observer
