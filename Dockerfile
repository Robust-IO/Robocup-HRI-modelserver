FROM vllm/vllm-omni:v0.32.0

RUN pip install --no-cache-dir 'sherpa-onnx==2.0.1'

WORKDIR /app
COPY scripts/ /app/scripts/
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
