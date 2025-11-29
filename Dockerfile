FROM python:3.10-alpine as base

RUN apk add --no-cache \
    git \
    wget \
    pv \
    jq \
    mediainfo \
    ffmpeg \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    libjpeg-turbo \
    libpng \
    libwebp \
    tiff \
    openjpeg \
    libimagequant \
    freetype \
    lcms2 \
    zlib \
    libgcc \
    libstdc++ \
    && apk add --no-cache --virtual .build-deps \
    build-base \
    && pip install --no-cache-dir --upgrade pip \
    && apk del .build-deps

ARG UID=1000
RUN adduser -D -u $UID appuser
WORKDIR /home/appuser/app
RUN chown appuser:appuser /home/appuser/app

COPY --chown=appuser:appuser requirements.txt .
USER appuser

RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=appuser:appuser . .

ENV PATH="/home/appuser/.local/bin:${PATH}"

CMD ["sh", "run.sh"]
