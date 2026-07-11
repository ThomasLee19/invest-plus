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

# requirements.txt 单独先 COPY 再 pip install，跟下面的 tiktoken/nltk 预烘一起，
# 是让这几层的 Docker 缓存只取决于 requirements.txt 有没有变——原来的顺序是先
# COPY 整个 backend/ 再装依赖，导致改一行业务代码（backend/ 下任何文件）都会
# 让这层缓存失效，逼着每次 pip install + tiktoken 下载 + nltk 下载全部重跑一遍
# （生产环境实测：改一行 finance_tool.py 触发的部署，构建耗时和首次冷构建几乎
# 一样长）。真正的 backend/ 源码 COPY 挪到最后，这样日常改代码只让最后这层和
# LFS 校验重新跑，前面这些重量级步骤都能命中缓存。
COPY requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

ENV TIKTOKEN_CACHE_DIR=/srv/investplus/.tiktoken_cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# rag_tokenizer.py 的 word_tokenize/WordNetLemmatizer 分别需要 punkt_tab/wordnet
# 语料，不预烘的话首次 PDF 上传会在运行时报 "Resource not found" 直接失败
# （本地验证时实测到的真实错误，不是预防性猜测）。跟 tiktoken 一样烘进镜像层，
# 避免生产环境依赖运行时联网下载（该 ECS 到 nltk 官方服务器的出网可达性未验证过）。
ENV NLTK_DATA=/srv/investplus/.nltk_data
RUN python -c "import nltk; nltk.download('punkt_tab', download_dir='${NLTK_DATA}'); nltk.download('wordnet', download_dir='${NLTK_DATA}')"

COPY backend/ ./backend/

RUN test $(stat -c%s backend/app/service/core/rag/res/deepdoc/det.onnx) -gt 1000000 || (echo "DeepDoc模型是LFS指针,不是真实文件,构建失败" && exit 1)

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["sh", "-c", "cd backend/app && uvicorn app_main:app --host 0.0.0.0 --port 8000"]
