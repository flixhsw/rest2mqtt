# http2mqtt

Make a HTTP interface accessible via MQTT.

## Purpose

This code and docker container makes device(s) with a HTTP interface accessible via MQTT.

Several devices at home, like a wallbox or a photovoltaics inverter, provide only HTTP interfaces.
Often, these are somehow limited: Due to little performance, they might only allow the be called with a limited rate (i.e. once per second) and can only handle a few clients.

When there are multiple clients polling these devices, one quickly gets into trouble:
 
* HTTP requests might arrive at a similar time at the device causing performance issues
* responses contain different data, which could cause problems when you expect clients are working on the same data.

That's where this container helps: It is the single client polling the HTTP interface of your device(s).
The retrieved information is then published via MQTT, from which multiple clients can consume without any performance issues.

HTTP endpoints can be polled, i.e. every 10 seconds.
Alternatively, HTTP requests can be triggered by certain MQTT messages.

## Configuration

See [configuration](doc/configuration.md).

## Running the container

### Via docker

`docker run -v ./config:/app/config http2mqtt`

### Via docker compose

Create a `docker-compose.yml` with the following content:

    services:
      http2mqtt:
        container_name: http2mqtt
        image: flixhsw/http2mqtt:latest
        volumes:
        - './config:/app/config'
        restart: unless-stopped

