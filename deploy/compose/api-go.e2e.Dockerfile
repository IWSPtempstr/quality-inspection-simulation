FROM golang:1.26 AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/api-worker ./cmd/worker

FROM alpine:3.20 AS worker-runtime
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /out/api-worker /app/api-worker
COPY --from=build /src/migrations /app/migrations
ENTRYPOINT ["/app/api-worker"]
