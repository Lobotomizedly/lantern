FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files - version bump forces cache invalidation
COPY frontend/package*.json ./

# Install dependencies fresh
RUN npm install --legacy-peer-deps

# Copy ALL source files in a single layer to avoid caching issues
COPY frontend/src/ ./src/
COPY frontend/public/ ./public/
COPY frontend/next.config.js frontend/tsconfig.json frontend/postcss.config.js frontend/tailwind.config.ts ./

# Verify the files contain Suspense fix
RUN echo "=== Verifying Suspense boundary in search/page.tsx ===" && \
    grep -n "Suspense" src/app/search/page.tsx || echo "WARNING: No Suspense found!" && \
    echo "=== Verifying Suspense boundary in timeline/page.tsx ===" && \
    grep -n "Suspense" src/app/timeline/page.tsx || echo "WARNING: No Suspense found!" && \
    echo "=== Checking next.config.js ===" && \
    cat next.config.js

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
