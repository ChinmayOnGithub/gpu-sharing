FROM ubuntu:22.04

# Install dependencies
RUN apt-get update -qq && apt-get install -y \
    python3 python3-pip curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip3 install requests kubernetes tenacity

# Create app directory
WORKDIR /app

# Copy scaler code
COPY gpu_scaler.py .

CMD ["python3", "gpu_scaler.py"]