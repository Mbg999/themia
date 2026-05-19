# Stage 1: Build the Angular application
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (better layer caching)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build for production
COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# Copy built Angular assets
# angular.json uses @angular/build:application with project name "thermia-front"
# Default output path: dist/thermia-front/browser
COPY --from=build /app/dist/thermia-front/browser /usr/share/nginx/html

# Copy nginx template — API_KEY is substituted at container start via envsubst
COPY nginx.conf.template /etc/nginx/conf.d/default.conf.template

EXPOSE 80

# envsubst replaces ${API_KEY} in the template before nginx starts.
# API_KEY must be provided at runtime (docker-compose env_file or -e flag).
CMD ["/bin/sh", "-c", "envsubst '${API_KEY}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
