FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files from frontend directory
COPY frontend/package*.json ./

# Install dependencies
RUN npm install

# Copy source code from frontend directory
COPY frontend/src/app/ ./src/app/
COPY frontend/src/components/ ./src/components/
COPY frontend/src/types/ ./src/types/
COPY frontend/src/lib/ ./src/lib/
COPY frontend/public/ ./public/
COPY frontend/next.config.js frontend/tsconfig.json frontend/postcss.config.js frontend/tailwind.config.ts ./

# Cache bust and debug: verify latest code
ARG CACHEBUST=1
RUN echo "Build timestamp: $(date)" && head -20 src/app/search/page.tsx | grep -E "Suspense|SearchPageContent" && head -20 src/app/timeline/page.tsx | grep -E "Suspense|TimelinePageContent"

# Set build-time environment variable
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Build the application
RUN npm run build

# Production image
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Copy built assets
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Expose port
EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
