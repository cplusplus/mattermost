FROM node:25-alpine

RUN apk add git

WORKDIR /usr/src/app
COPY package.json ./
RUN yarn --non-interactive install
COPY ./src ./src

ENV CAPTURE_CONSOLE=1
EXPOSE 3000
CMD ["yarn", "run", "start"]
