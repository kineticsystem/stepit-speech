#!/bin/bash -e

# Everything CI checks, in the order it checks it: the style, every robot file
# with all its examples, and the tests. Run it in the container with
# ./docker/dock.sh test, or in a virtual environment with the dev extras.

cd "$(dirname "$0")/.."

echo "== ruff"
ruff check src tests

echo "== robot files"
for robot in robots/*/robot.yaml; do
    voicebridge check "$robot" > /dev/null
    echo "$robot: ok"
done

echo "== tests"
# -p no:cacheprovider: no .pytest_cache in the mounted repo.
python -m pytest -q -p no:cacheprovider "$@"
