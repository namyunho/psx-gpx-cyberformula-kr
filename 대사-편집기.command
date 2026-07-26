#!/bin/zsh

# Finder에서 더블클릭하거나 터미널에서 실행하는 대사 편집기 실행기.

set -u

launcher_path="${0:A}"
project_dir="${launcher_path:h}"
python_path="${project_dir}/.venv/bin/python"

pause_and_exit() {
    local exit_code="$1"
    shift
    print -u2 ""
    print -u2 "오류: $*"
    if [[ -t 0 ]]; then
        print -u2 ""
        read -k 1 "?아무 키나 누르면 창을 닫습니다."
        print
    fi
    exit "${exit_code}"
}

cd "${project_dir}" || pause_and_exit 1 "프로젝트 폴더를 열 수 없습니다."

if [[ ! -x "${python_path}" ]]; then
    pause_and_exit 1 \
        ".venv Python이 없습니다. 프로젝트 설정 문서에 따라 가상환경을 먼저 준비하세요."
fi

required_files=(
    "work/translations/disc1-dialogue-ko-candidate.json"
    "work/translations/disc1-dialogue.json"
    "work/extracted/disc1/iso/ALLBIN.BIN"
)

for required_file in "${required_files[@]}"; do
    if [[ ! -f "${project_dir}/${required_file}" ]]; then
        pause_and_exit 1 "필수 파일이 없습니다: ${required_file}"
    fi
done

print "안전 슬롯 자료를 원본 ALLBIN에서 갱신합니다."
"${python_path}" scripts/build_dialogue_safe_slots.py \
    --workset work/translations/disc1-dialogue.json \
    --allbin work/extracted/disc1/iso/ALLBIN.BIN \
    --output work/analysis/disc1-dialogue-safe-slots.json \
    --csv-output work/analysis/disc1-dialogue-safe-slots.csv \
    || pause_and_exit 1 "안전 슬롯 자료 생성에 실패했습니다."

print ""
print "대사 편집기를 실행합니다."
exec "${python_path}" scripts/dialogue_layout_editor.py \
    --input work/translations/disc1-dialogue-ko-candidate.json \
    --workset work/translations/disc1-dialogue.json \
    --safe-slots work/analysis/disc1-dialogue-safe-slots.json \
    "$@"
