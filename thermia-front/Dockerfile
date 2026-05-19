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

# Copy custom nginx config (replaces default)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
