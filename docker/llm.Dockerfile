# The image of the LLM: llama-server of the submodule engines/llama.cpp, built
# with CUDA for one GPU architecture. The build context is engines/llama.cpp;
# docker/compose.yaml builds it, and starts it on the model of models/.
#
# CUDA 13.0 matches the CUDA of the 580 driver series. The test image needs
# none of this: the tests use a fake LLM.

ARG CUDA_VERSION=13.0.2

FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu24.04 AS build

# 89 is the RTX 4090; GGML_CUDA=OFF builds for the CPU only, e.g. to try it without a GPU.
ARG CUDA_ARCHITECTURES=89
ARG GGML_CUDA=ON

RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

# No web UI: the bridge is the only client, and the prebuilt one would be downloaded at build time.
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DGGML_CUDA=${GGML_CUDA} -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCHITECTURES} \
        -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
        -DLLAMA_CURL=OFF \
    && cmake --build build --target llama-server -j "$(nproc)"

FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu24.04

# The forward-compatibility libraries of the CUDA image work on datacenter GPUs only: on a
# GeForce card every CUDA call fails with cudaErrorCompatNotSupportedOnDevice.
RUN rm -rf /usr/local/cuda*/compat \
    && apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/build/bin/llama-server /usr/local/bin/llama-server

ENTRYPOINT ["llama-server"]
