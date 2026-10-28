# The image of the speech server: Hugging Face Speech-to-Speech of the submodule
# engines/speech-to-speech, with its default speech-to-text, Parakeet, and voice,
# Qwen3-TTS on GGML. The build context is engines/speech-to-speech;
# docker/compose.yaml builds it, and starts it after the bridge.
#
# It follows the submodule's own Dockerfile, with two changes: NLTK's data goes
# to /usr/share/nltk_data, not /root, and HOME is /home/voice, writable by any
# user, so that it runs as the host's user and the models it downloads, mounted
# from the host's ~/.cache, stay the user's.

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PATH=/usr/src/app/.venv/bin:$PATH
ENV HOME=/home/voice

# The forward-compatibility libraries of the CUDA image work on datacenter GPUs only,
# as in llm.Dockerfile: on a GeForce card every CUDA call would fail.
RUN rm -rf /usr/local/cuda*/compat \
    && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git libportaudio2 libsndfile1 python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir --break-system-packages uv \
    && mkdir -p $HOME && chmod 1777 $HOME

WORKDIR /usr/src/app

# The dependencies first, so that a change of the code does not install them again. The
# submodule has no uv.lock: they are resolved from pyproject.toml at build time.
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
RUN uv sync --python /usr/bin/python3 --no-install-project --no-dev --no-cache

COPY . .
RUN uv sync --python /usr/bin/python3 --no-dev --no-cache \
    && python -c "import nltk; [nltk.download(name, download_dir='/usr/share/nltk_data') \
        for name in ('punkt_tab', 'averaged_perceptron_tagger_eng')]"

ENTRYPOINT ["speech-to-speech"]
