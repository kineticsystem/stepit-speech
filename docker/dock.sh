#!/bin/bash -e

# Builds the image of StepIt Speech and runs the tests or the bridge in
# it, with the repo mounted at /app, so that the image needs no rebuild after a
# change of the code.
#
#   ./docker/dock.sh build                 the image
#   ./docker/dock.sh test                  bin/test.sh, as CI runs it
#   ./docker/dock.sh serve [robot file]    the bridge, on the host's network
#   ./docker/dock.sh shell                 a terminal in the container

IMAGE=stepit-speech
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROBOT=${2:-robots/stepit-macro/robot.yaml}

# The host's user, so that files written in the mounted repo stay the user's.
RUN=(docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:/app" -w /app)

case "$1" in
    build)
        docker build -f "$ROOT/docker/Dockerfile" -t "$IMAGE" "$ROOT"
        ;;
    test)
        "${RUN[@]}" "$IMAGE" bin/test.sh
        ;;
    serve)
        # The host's network: the bridge reaches the speech server, rosbridge, the LLM
        # and the browser on the host's ports, e.g. 8765, 9090, 8085 and 8766, and the
        # speech server reaches its LLM proxy on 8767.
        "${RUN[@]}" -it --network host -e VOICEBRIDGE_UPSTREAM -e VOICEBRIDGE_ROSBRIDGE -e VOICEBRIDGE_LISTEN \
            -e VOICEBRIDGE_LLM_LISTEN -e VOICEBRIDGE_LLM_URL -e VOICEBRIDGE_LLM_MODEL \
            "$IMAGE" voicebridge serve "$ROBOT"
        ;;
    shell)
        "${RUN[@]}" -it --network host "$IMAGE" bash
        ;;
    *)
        echo "Usage: $0 build | test | serve [robot file] | shell"
        exit 1
        ;;
esac
