FROM nginx:alpine
# 不在镜像里 COPY 任何 default.conf——nginx.conf（生产）/nginx.local.conf（本地）
# 由 docker-compose 在容器启动时挂载为 /etc/nginx/conf.d/default.conf，避免镜像内置配置
# 覆盖或与挂载冲突。
