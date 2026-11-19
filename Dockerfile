# Epistemic Harness Backend — 一体化容器：代理网关 + MCP-over-HTTP 双服务
# 单端口 8787：/v1 (OpenAI) + /anthropic + /mcp/epistemic + /mcp/orchestrator
# 配置与密钥全部运行时挂载，绝不烘焙进镜像。

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proxy_gateway/ ./proxy_gateway/
COPY mcp_server/ ./mcp_server/
COPY orchestrator/ ./orchestrator/
COPY harness_backend.py .

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=2)" || exit 1

# 容器内必须监听 0.0.0.0；宿主机侧由 compose 绑定到 127.0.0.1，不对外暴露。
CMD ["python", "-m", "uvicorn", "harness_backend:app", "--host", "0.0.0.0", "--port", "8787"]
