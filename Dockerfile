# build: docker buildx build --platform linux/amd64 -f Dockerfile -t wzdnzd/aggregator:tag --build-arg PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple" .

FROM python:3.12.3-slim

LABEL maintainer="wzdnzd"

# token for storage backend, e.g. github personal access token
ENV PUSH_TOKEN=""

# process config file path or remote url
ENV SUBSCRIBE_CONF=""

# github token for code search crawler
ENV GH_TOKEN=""

# pip default index url
ARG PIP_INDEX_URL="https://pypi.org/simple"

WORKDIR /aggregator

# copy files, only linux related files are needed
COPY requirements.txt /aggregator
COPY subscribe /aggregator/subscribe 
COPY clash/clash-linux-amd clash/Country.mmdb /aggregator/clash

COPY subconverter /aggregator/subconverter
RUN rm -rf subconverter/subconverter-darwin-amd \
    && rm -rf subconverter/subconverter-darwin-arm \
    && rm -rf subconverter/subconverter-linux-arm \
    && rm -rf subconverter/subconverter-windows.exe

# install dependencies
RUN pip install -i ${PIP_INDEX_URL} --no-cache-dir -r requirements.txt

# start and run
CMD ["python", "-u", "subscribe/process.py", "--overwrite"]
