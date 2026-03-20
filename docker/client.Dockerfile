# Browser client container placeholder.

FROM node:20-alpine

WORKDIR /app
COPY web /app/web

CMD ["sh", "-c", "echo 'client container placeholder: add bundler and static server' && sleep infinity"]
