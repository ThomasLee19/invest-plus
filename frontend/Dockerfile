FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# frontend/.env 本身不含密钥（只有VITE_TITLE/VITE_API_BASE这类构建期常量），但仓库
# .gitignore统一排除了所有.env文件，导致CI/服务器这种全新clone的构建环境里.env缺失
# ——Vite读不到VITE_API_BASE，index.html里的%VITE_TITLE%占位符也替换不了。生产环境
# 实测复现过：baseURL被烘成void 0，浏览器发出的API请求全部丢了/ai-search前缀，命中
# frontend自己的nginx而不是backend，404。用.env.example兜底（值本来就跟.env一致，
# 只是本地开发额外多一个不影响构建的VITE_API_PROXY_BAK）。
RUN test -f .env || cp .env.example .env
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# 没有这份配置，nginx:alpine 的默认 server 块不做 SPA fallback，直接访问或刷新
# /repository、/chat/<id> 会由 nginx 返回 404（请求根本进不到 React，
# src/pages/404.tsx 救不了）。npm run dev 下 Vite 自带 fallback，所以这是一个
# 只在生产暴露的 dev/prod 分歧。
COPY nginx.conf /etc/nginx/conf.d/default.conf
HEALTHCHECK --interval=10s --timeout=3s CMD wget -q --spider http://localhost:80/ || exit 1
