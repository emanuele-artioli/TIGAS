# Renderer service container placeholder.
#
# Intended usage:
# - Include GPU runtime dependencies (CUDA or vendor-specific stack).
# - Install TIGAS package and renderer backend dependencies.
# - Expose renderer RPC endpoint consumed by orchestrator.

FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
ENV PYTHONPATH=/app/src

CMD ["python", "-c", "print('renderer container placeholder: implement service entrypoint')"]
