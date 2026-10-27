#!/bin/bash -e

# Downloads the LLM of the voice, Ternary Bonsai 2 27B, into models/, pinned to
# one revision of its repository on Hugging Face. An interrupted download
# resumes; the file gets its final name only once its SHA-256 is right, so a
# file of that name is always whole and nothing is checked twice.
#
#   bin/download-model.sh [directory]      models/ by default
#
# ./docker/dock.sh serve runs it before it starts the LLM.

REPO=prism-ml/Ternary-Bonsai-2-27B-gguf-dev
REVISION=2a263ef827a2e215f3ddd14c9871a5bd1800fcbc
FILE=Ternary-Bonsai-2-27B-Q2_0-prism-fork-required.gguf
SHA256=4f99aed01b8a877e153f9aa6569a4440fe17c59701cc0953e36d7f460549e70e
SIZE=7626008928

cd "$(dirname "$0")/.."
DIR=${1:-models}
target=$DIR/$FILE
partial=$target.part

if [ -e "$target" ]; then
    echo "$target: already downloaded"
    exit 0
fi

mkdir -p "$DIR"
# A partial file already whole: curl would ask for bytes past its end.
if [ "$(stat -c %s "$partial" 2>/dev/null || echo 0)" -lt "$SIZE" ]; then
    echo "Downloading $FILE, 7.6 GB, into $DIR"
    curl -fL --retry 5 --retry-delay 5 -C - -o "$partial" "https://huggingface.co/$REPO/resolve/$REVISION/$FILE"
fi

echo "Checking its SHA-256"
if ! echo "$SHA256  $partial" | sha256sum -c --quiet; then
    rm -f "$partial"
    echo "$FILE: the SHA-256 is wrong, so the download was deleted. Run it again." >&2
    exit 1
fi
mv "$partial" "$target"
echo "$target: ok"
