#!/bin/bash -e

# Builds the images of StepIt Speech and runs the tests, the voice's LLM or the
# bridge in them, with the repo mounted at /app, so that the bridge's image needs
# no rebuild after a change of the code.
#
#   ./docker/dock.sh build                 the image of the bridge and the tests
#   ./docker/dock.sh build-llm             the image of llama-server, with CUDA (about 10 minutes on 12 cores)
#   ./docker/dock.sh test                  bin/test.sh, as CI runs it
#   ./docker/dock.sh models                downloads the model into models/
#   ./docker/dock.sh serve [robot file]    the LLM on the GPU, then the bridge, on the host's network
#   ./docker/dock.sh bridge [robot file]   the bridge alone, with an LLM of our own at VOICEBRIDGE_LLM_URL
#   ./docker/dock.sh shell                 a terminal in the container

IMAGE=stepit-speech
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROBOT=${2:-robots/stepit-macro/robot.yaml}

# The host's user, so that files written in the mounted repo stay the user's.
RUN=(docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:/app" -w /app)
COMPOSE=(docker compose -f "$ROOT/docker/compose.yaml")

# llama.cpp is a submodule: a clone without --recursive does not have it yet.
llama_cpp() {
    [ -e "$ROOT/engines/llama.cpp/CMakeLists.txt" ] || git -C "$ROOT" submodule update --init engines/llama.cpp
}

case "$1" in
    build)
        docker build -f "$ROOT/docker/Dockerfile" -t "$IMAGE" "$ROOT"
        ;;
    build-llm)
        llama_cpp
        "${COMPOSE[@]}" build llm
        ;;
    test)
        "${RUN[@]}" "$IMAGE" bin/test.sh
        ;;
    models)
        "$ROOT/bin/download-model.sh"
        ;;
    serve)
        llama_cpp
        "$ROOT/bin/download-model.sh"
        export ROBOT HOST_UID HOST_GID
        HOST_UID=$(id -u) HOST_GID=$(id -g)
        # Ctrl-C, or the end of either, stops both.
        trap '"${COMPOSE[@]}" down' EXIT
        "${COMPOSE[@]}" up --abort-on-container-exit
        ;;
    bridge)
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
        echo "Usage: $0 build | build-llm | test | models | serve [robot file] | bridge [robot file] | shell"
        exit 1
        ;;
esac
