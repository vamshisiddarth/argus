FROM python:3.13-slim

WORKDIR /app

# Install cloud-specific deps at build time via ARG
# docker build --build-arg CLOUD=aws -t argus .
ARG CLOUD=aws

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/${CLOUD}.txt

COPY . .

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
