#!/bin/bash
set -e

echo "=== SSD exFAT 포맷 시작 ==="
echo ""

# sde3 언마운트 (이미 됐어도 무시)
umount /dev/sde3 2>/dev/null || true

declare -A LABELS=(
    ["sdb"]="SSD_0"   # Samsung 860 EVO
    ["sdc"]="SSD_1"   # Samsung 850 EVO
    ["sdd"]="SSD_2"   # Samsung 850 EVO
    ["sde"]="SSD_3"   # Samsung 850 EVO
)

for DEV in sdb sdc sdd sde; do
    LABEL="${LABELS[$DEV]}"
    echo "── /dev/$DEV → $LABEL ──────────────────────────"

    # 기존 파티션/서명 완전 삭제
    wipefs -af /dev/$DEV

    # GPT 파티션 테이블 + 단일 파티션
    parted -s /dev/$DEV mklabel gpt
    parted -s /dev/$DEV mkpart "$LABEL" 0% 100%

    # 커널이 파티션 테이블을 다시 읽도록
    partprobe /dev/$DEV
    sleep 1

    # exFAT 포맷
    mkfs.exfat -n "$LABEL" /dev/${DEV}1

    echo "  완료: /dev/${DEV}1 → exFAT, label=$LABEL"
    echo ""
done

echo "=== 포맷 완료 ==="
lsblk -o NAME,SIZE,LABEL,FSTYPE /dev/sdb /dev/sdc /dev/sdd /dev/sde
