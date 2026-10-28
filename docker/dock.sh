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

# The containers cannot resolve mDNS names, e.g. stepit.local: the host resolves each
# one named by the robot file or the bridge's variables, and the bridge gets it as an
# --add-host, or as an extra host of compose.
function mdns_hosts() {
    local names name address
    names=$( (cat "$ROOT/$ROBOT" 2>/dev/null; echo "$VOICEBRIDGE_ROSBRIDGE $VOICEBRIDGE_UPSTREAM $VOICEBRIDGE_LLM_URL") \
        | grep -oE '[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.local\b' | sort -u)
    for name in $names; do
        address=$(getent ahostsv4 "$name" | awk 'NR == 1 { print $1 }')
        if [ -z "$address" ]; then
            echo "Cannot resolve $name: is the machine on the network?" >&2
            exit 1
        fi
        HOSTS+=("$name:$address")
        ADD_HOSTS+=(--add-host "$name:$address")
    done
}
HOSTS=()
ADD_HOSTS=()

# The extra hosts of the bridge, as a compose file that docker/compose.yaml is merged with.
function mdns_compose() {
    local host
    echo "services:"
    echo "  bridge:"
    echo "    extra_hosts: ["
    for host in "${HOSTS[@]}"; do
        echo "      \"$host\","
    done
    echo "    ]"
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
        mdns_hosts
        HOSTS_FILE=$(mktemp --suffix .yaml)
        mdns_compose > "$HOSTS_FILE"
        COMPOSE+=(-f "$HOSTS_FILE")
        # Ctrl-C, or the end of either, stops both.
        trap '"${COMPOSE[@]}" down; rm -f "$HOSTS_FILE"' EXIT
        "${COMPOSE[@]}" up --abort-on-container-exit
        ;;
    bridge)
        # The host's network: the bridge reaches the speech server, rosbridge, the LLM
        # and the browser on the host's ports, e.g. 8765, 9090, 8085 and 8766, and the
        # speech server reaches its LLM proxy on 8767.
        mdns_hosts
        "${RUN[@]}" -it --network host "${ADD_HOSTS[@]}" -e VOICEBRIDGE_UPSTREAM -e VOICEBRIDGE_ROSBRIDGE -e VOICEBRIDGE_LISTEN \
            -e VOICEBRIDGE_LLM_LISTEN -e VOICEBRIDGE_LLM_URL -e VOICEBRIDGE_LLM_MODEL \
            "$IMAGE" voicebridge serve "$ROBOT"
        ;;
    shell)
        mdns_hosts
        "${RUN[@]}" -it --network host "${ADD_HOSTS[@]}" "$IMAGE" bash
        ;;
    *)
        echo "Usage: $0 build | build-llm | test | models | serve [robot file] | bridge [robot file] | shell"
        exit 1
        ;;
esac
