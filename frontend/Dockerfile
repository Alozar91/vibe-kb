# Frontend: сборка Vite + nginx (deployment.md §1: base /know/)
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# envsubst: подстановка API_HOST/MCP_HOST/KC_HOST из environment контейнера
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV API_HOST=api MCP_HOST=mcp KC_HOST=keycloak
EXPOSE 80
