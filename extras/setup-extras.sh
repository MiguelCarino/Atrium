#!/usr/bin/env bash
# The smart extras: the models and Python packages behind the features that
# hear, speak and see. Each lives in a venv of its own under ~/.local/share,
# where the scripts look for it; nothing is installed system-wide. Safe to
# run again (a step already done is skipped). Run it any time after install.sh:
#
#   extras/setup-extras.sh            all three
#   extras/setup-extras.sh voice      only speech-to-text   (~1-3 GB)
#   extras/setup-extras.sh tts        only the voices       (~200 MB)
#   extras/setup-extras.sh camera     only the camera models (~150 MB)
#
#   voice   faster-whisper (voice typing, captions, voice commands); with an
#           NVIDIA card also its CUDA libraries, so it runs on the GPU
#   tts     Piper and one English voice (Settings > Speech offers more)
#   camera  OpenCV and three small ONNX models: the face detector (presence)
#           and the hand models (gestures). The features stay OFF until you
#           turn them on in Settings > Privacy.
set -euo pipefail

DATA=${XDG_DATA_HOME:-$HOME/.local/share}
HYPR=$HOME/.config/hypr/scripts
ZOO=https://github.com/opencv/opencv_zoo/raw/main/models

venv() {  # venv DIR PKG... -- create once, then make sure the packages are in
    local dir=$1; shift
    [[ -x $dir/venv/bin/python ]] || python3 -m venv "$dir/venv"
    "$dir/venv/bin/pip" install -q --upgrade pip
    "$dir/venv/bin/pip" install -q "$@"
}
fetch() {  # fetch URL FILE
    [[ -s $2 ]] && return 0
    curl -fL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"
}

voice() {
    echo "== speech-to-text =="
    local pkgs=(faster-whisper)
    command -v nvidia-smi >/dev/null && pkgs+=(nvidia-cublas-cu12 nvidia-cudnn-cu12)
    venv "$DATA/voice" "${pkgs[@]}"
    echo "  the model downloads on first use (Settings > Voice picks its size)"
}
tts() {
    echo "== voices =="
    venv "$DATA/tts" piper-tts
    python3 "$HYPR/tts.py" download en_US-lessac-medium
}
camera() {
    echo "== camera models =="
    venv "$DATA/presence" opencv-python-headless numpy
    fetch "$ZOO/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
          "$DATA/presence/face_detection_yunet_2023mar.onnx"
    fetch "$ZOO/palm_detection_mediapipe/palm_detection_mediapipe_2023feb.onnx" \
          "$DATA/presence/palm_detection_mediapipe_2023feb.onnx"
    fetch "$ZOO/handpose_estimation_mediapipe/handpose_estimation_mediapipe_2023feb.onnx" \
          "$DATA/presence/handpose_estimation_mediapipe_2023feb.onnx"
}

mkdir -p "$DATA"
case ${1:-all} in
voice) voice ;;
tts) tts ;;
camera) camera ;;
all) voice; tts; camera ;;
*) sed -n '2,18p' "$0"; exit 2 ;;
esac
echo "Done."
