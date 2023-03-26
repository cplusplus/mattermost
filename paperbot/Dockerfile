FROM node:16-alpine
RUN apk add git
WORKDIR /usr/src/app
COPY package.json ./
RUN yarn --non-interactive install
COPY ./src ./src
EXPOSE 3000
CMD yarn run start
