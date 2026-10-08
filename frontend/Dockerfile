FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_CONTACT_EMAIL
ENV VITE_CONTACT_EMAIL=$VITE_CONTACT_EMAIL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
ENV MEDIA_ORIGIN="http://localhost:9000" API_UPSTREAM="backend:8000"
EXPOSE 80
