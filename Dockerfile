# OpenShift-compatible image for the Adhesion analysis app.
#
# Build with podman, buildah or an OpenShift Docker-strategy build:
#   podman build -t adhesion:latest .
#
# Run locally:
#   podman run --rm -p 8080:8080 adhesion:latest
#
# OpenShift runs containers with an arbitrary UID that is always a member of
# group 0.  Everything the app needs to read is therefore group-readable, and
# every runtime write directory is group-writable.
FROM registry.access.redhat.com/ubi9/python-312-minimal:latest

ENV APP_ROOT=/opt/app-root \
    HOME=/opt/app-root/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/app-root/src

# Copy requirements first so dependency layers survive source-only changes.
# The UBI Python image is already writable by UID 1001:0, so the whole build
# stays rootless.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=1001:0 . .

# Runtime data: uploads, pair manifests, analysis caches, rendered views and
# reconstructed demo TIFFs.  OpenShift can mount a PVC at data/; the directory
# remains group-writable for arbitrary UIDs when the volume has an fsGroup.
# The rm also keeps a stale host data/ tree out of the image if a build tool
# ignores .dockerignore.
RUN rm -rf data \
    && mkdir -p data/uploads data/pairs data/cache data/runs data/demo \
    && chgrp -R 0 /opt/app-root/src \
    && chmod -R g+rwX /opt/app-root/src

# Keep the image's normal user for podman/docker.  OpenShift replaces this
# with its namespace UID while preserving supplementary group 0.
USER 1001

EXPOSE 8080

# The analysis is CPU-bound and the on-disk cache assumes one writer.  A
# single synchronous worker serialises analyses so two requests cannot write
# the same cache entry at once; extra requests wait briefly in the backlog.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "1", "--timeout", "900", "--graceful-timeout", "30", "--access-logfile=-", "--error-logfile=-", "app:app"]
