# CUDA base image — matches your driver (590.48.01 → CUDA 12.x)
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

# Avoid interactive prompts during apt
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && \
    apt-get install -y python3 python3-pip curl && \
    rm -rf /var/lib/apt/lists/*

# CuPy for CUDA 12.x  (cupy-cuda12x covers CUDA 12.0–12.x)
# flask + psutil for the web app
RUN pip3 install --no-cache-dir \
    cupy-cuda12x \
    flask \
    requests \
    psutil

# Create app directory
WORKDIR /app

# Copy application code
COPY gpu_app.py .

EXPOSE 8080

CMD ["python3", "gpu_app.py"]