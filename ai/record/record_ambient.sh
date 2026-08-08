#!/bin/sh
# 일상 소음을 길게 녹음한다 (오알림 측정용).
#
# 위험음(사이렌·유리·노크·불)이 나지 않는 평범한 시간대에 걸어두고 생활하면 된다.
# 10분 단위로 파일을 나눠 저장하므로 도중에 멈춰도 그때까지 녹음한 건 남는다.
#
# 사용법:
#   ./record_ambient.sh                 기본 장치, 2시간
#   ./record_ambient.sh plughw:1,0      장치 지정
#   ./record_ambient.sh plughw:1,0 4    장치 지정 + 4시간

set -u

DEVICE="${1:-}"
HOURS="${2:-2}"

CHUNK_SEC=600          # 10분
RATE=44100
OUT="$(dirname "$0")/../dataset/realworld/ambient"

mkdir -p "$OUT"

CHUNKS=$(awk "BEGIN{printf \"%d\", $HOURS * 3600 / $CHUNK_SEC}")
STAMP=$(date +%Y%m%d_%H%M)

echo "======================================================"
echo " 일상 소음 녹음"
echo "======================================================"
echo " 저장 위치 : $OUT"
echo " 총 시간   : ${HOURS}시간  (10분 x ${CHUNKS}개 파일)"
echo " 장치      : ${DEVICE:-기본}"
echo
echo " 주의: 이 시간 동안 사이렌·유리 깨짐·노크 소리가 나면 안 됩니다."
echo "       창밖 구급차 등 예외가 있었다면 시각을 메모해 주세요."
echo
echo " 중단하려면 Ctrl+C (그때까지 녹음한 파일은 남습니다)"
echo "======================================================"
echo

i=1
while [ "$i" -le "$CHUNKS" ]; do
    FILE=$(printf "%s/ambient_%s_%02d.wav" "$OUT" "$STAMP" "$i")
    printf "[%2d/%d] %s ... " "$i" "$CHUNKS" "$(basename "$FILE")"

    if [ -n "$DEVICE" ]; then
        arecord -D "$DEVICE" -f S16_LE -r "$RATE" -c 1 -d "$CHUNK_SEC" -t wav "$FILE" 2>/dev/null
    else
        arecord -f S16_LE -r "$RATE" -c 1 -d "$CHUNK_SEC" -t wav "$FILE" 2>/dev/null
    fi

    if [ $? -ne 0 ]; then
        echo "실패"
        echo
        echo "녹음에 실패했습니다. 장치 이름을 확인하세요:"
        echo "  arecord -l"
        echo "  python3 check_mic.py plughw:1,0"
        exit 1
    fi

    echo "완료"
    i=$((i + 1))
done

echo
echo "녹음 완료. 파일 목록:"
ls -lh "$OUT"
echo
echo "이 폴더를 PC로 옮긴 뒤 eval_stream.py 로 시간당 오알림을 측정하면 됩니다."
