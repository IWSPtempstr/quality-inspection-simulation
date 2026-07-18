FROM golang:1.26 AS build

WORKDIR /src/services/api-go
COPY services/api-go/go.mod services/api-go/go.sum ./
RUN go mod download
COPY services/api-go ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/api-go ./cmd/api
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/api-worker ./cmd/worker

FROM alpine:3.20 AS api-runtime
RUN apk add --no-cache ca-certificates wget
WORKDIR /app
COPY --from=build /out/api-go /app/api-go
COPY services/api-go/migrations /app/migrations
EXPOSE 8080
ENTRYPOINT ["/app/api-go"]

FROM alpine:3.20 AS worker-runtime
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /out/api-worker /app/api-worker
COPY services/api-go/migrations /app/migrations
ENTRYPOINT ["/app/api-worker"]
