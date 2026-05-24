#!/usr/bin/env python3
"""
사진 파이프라인 오케스트레이터

실행:  python main.py

상시:  SD/CF 카드 감지 → inbox 복사 → sorted 분류 (ntfy 알림)
새벽 4시: sorted → HDD 배포 (ntfy 알림)
매주 일요일 새벽 3시: HDD 무결성 검사 (ntfy 알림)
"""
import json
import os
import sys
import time
from datetime import datetime

import schedule

from config import (
    CHECK_AT, CHECK_WEEKDAY, DISTRIBUTE_AT,
    INBOX_DIR, SORTED_DIR, STATE_FILE, VIDEO_SORTED_DIR,
)
from importer import start_watcher
from distributor import distribute, distribute_videos
from checker import run_integrity_check
from notifier import notify


_WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _ensure_dirs():
    for d in (INBOX_DIR, SORTED_DIR, VIDEO_SORTED_DIR):
        os.makedirs(d, exist_ok=True)


# ── 상태 파일 (스케줄 누락 감지) ────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[상태] 저장 실패: {e}")


# ── 스케줄 job 래퍼 (예외 격리 + 상태 기록) ─────────────────────────────────────

def _wrapped_distribute():
    try:
        distribute()
    except Exception as e:
        print(f"[배포 오류] {e}")
        notify("⚠️ 배포 오류", str(e), priority="high", tags=["warning"])
        return
    # 사진 배포 성공 기록 (재시작 시 재실행 방지)
    state = _load_state()
    state["distribute_last_run"] = datetime.now().strftime("%Y-%m-%d")
    _save_state(state)
    try:
        distribute_videos()
    except Exception as e:
        print(f"[영상 배포 오류] {e}")
        notify("⚠️ 영상 배포 오류", str(e), priority="high", tags=["warning"])


def _wrapped_integrity_check():
    try:
        run_integrity_check()
    except Exception as e:
        print(f"[무결성 검사 오류] {e}")
        notify("⚠️ 무결성 검사 오류", str(e), priority="high", tags=["warning"])
        return
    state = _load_state()
    state["check_last_run"] = datetime.now().strftime("%Y-%m-%d")
    _save_state(state)


# ── 재시작 시 누락 스케줄 즉시 실행 ──────────────────────────────────────────────

def _catch_up_missed_jobs():
    state = _load_state()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    now_minutes = now.hour * 60 + now.minute

    dist_h, dist_m = map(int, DISTRIBUTE_AT.split(":"))
    if state.get("distribute_last_run") != today and now_minutes >= dist_h * 60 + dist_m:
        print(f"[스케줄] {DISTRIBUTE_AT} 배포 누락 감지 → 즉시 실행")
        _wrapped_distribute()

    check_weekday_num = _WEEKDAY_MAP.get(CHECK_WEEKDAY, 6)
    check_h, check_m = map(int, CHECK_AT.split(":"))
    if (now.weekday() == check_weekday_num
            and state.get("check_last_run") != today
            and now_minutes >= check_h * 60 + check_m):
        print(f"[스케줄] {CHECK_AT} 무결성 검사 누락 감지 → 즉시 실행")
        _wrapped_integrity_check()


def main():
    _ensure_dirs()

    # ── 카드 감시 시작 ──────────────────────────────────────────────────────────
    observer = start_watcher()

    # ── 재시작 시 누락된 스케줄 복구 ───────────────────────────────────────────
    _catch_up_missed_jobs()

    # ── 스케줄 등록 ─────────────────────────────────────────────────────────────
    schedule.every().day.at(DISTRIBUTE_AT).do(_wrapped_distribute)
    getattr(schedule.every(), CHECK_WEEKDAY).at(CHECK_AT).do(_wrapped_integrity_check)

    print(f"\n파이프라인 시작")
    print(f"  {DISTRIBUTE_AT} 매일: HDD 배포")
    print(f"  {CHECK_AT} 매주 {CHECK_WEEKDAY}: 무결성 검사")
    print(f"  inbox  → {INBOX_DIR}")
    print(f"  sorted → {SORTED_DIR}")
    print("  종료: Ctrl+C\n")

    try:
        while True:
            # ── Fix #2: schedule job 예외가 main loop를 크래시시키지 않도록 ────
            try:
                schedule.run_pending()
            except Exception as e:
                print(f"[스케줄 오류] {e}")
                notify("⚠️ 스케줄 오류", str(e), priority="high", tags=["warning"])

            # ── Fix #3: Observer 스레드 크래시 감지 및 재시작 ───────────────────
            if not observer.is_alive():
                print("[경고] 카드 감시 스레드가 비정상 종료됨. 재시작 중...")
                try:
                    observer.stop()
                    observer.join(timeout=5)  # inotify fd 즉시 해제
                except Exception:
                    pass
                observer = start_watcher()
                notify(
                    "⚠️ 카드 감시 재시작",
                    "Observer 스레드 비정상 종료 후 재시작됨",
                    priority="high",
                    tags=["warning"],
                )

            time.sleep(30)
    except KeyboardInterrupt:
        print("\n종료 중...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    # pipeline/ 디렉터리를 sys.path에 추가 (상대 import 지원)
    sys.path.insert(0, os.path.dirname(__file__))
    main()
