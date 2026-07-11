FROM python:3.11-slim

# libglib2.0-0/libgomp1: onnxruntime/xgboost 运行时依赖。
# build-essential: requirements.txt 里的 datrie==0.8.3（nltk分词器依赖）在这个
# 平台/Python版本组合下没有预编译wheel，pip 会退回源码编译，需要 gcc/make——
# python:3.11-slim 默认不带，缺了会在 pip install 阶段报 "gcc: No such file
# or directory" 直接构建失败（首次构建时实测到的真实错误，非预防性猜测）。
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/investplus

COPY backend/ ./backend/
COPY requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

ENV TIKTOKEN_CACHE_DIR=/srv/investplus/.tiktoken_cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

RUN test $(stat -c%s backend/app/service/core/rag/res/deepdoc/det.onnx) -gt 1000000 || (echo "DeepDoc模型是LFS指针,不是真实文件,构建失败" && exit 1)

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["sh", "-c", "cd backend/app && uvicorn app_main:app --host 0.0.0.0 --port 8000"]
