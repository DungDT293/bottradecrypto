FROM python:3.11-slim

LABEL maintainer="Quantum AI Trader <leon@stark-quantum.ai>"
LABEL description="Jarvis Quantum AI Trading Bot 24/7"

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt múi giờ Việt Nam UTC+7
ENV TZ=Asia/Ho_Chi_Minh
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . /app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import psutil; sys.exit(0)" || exit 1

CMD ["python", "-u", "-m", "telegram.dedicated_bot"]

