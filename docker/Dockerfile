# The image of StepIt Speech: the bridge, its tests and its tools. It
# needs no ROS: the bridge reaches the robot through rosbridge, over a
# WebSocket. CI builds it and runs bin/test.sh in it; ./docker/dock.sh serve
# runs the bridge in it.

FROM python:3.12-slim

WORKDIR /app

# The dependencies first, so that a change of the code does not install them again.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --editable '.[dev]'

COPY . .

# The browser connects to the bridge here.
EXPOSE 8766

CMD ["voicebridge", "serve", "robots/stepit-macro/robot.yaml"]
