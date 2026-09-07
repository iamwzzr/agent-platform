FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime

COPY --chown=101:101 nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=101:101 /app/dist/ /usr/share/nginx/html/

USER 101

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
